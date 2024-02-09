from summarizer import summarize
from llm import llm
import database
import settings
from sqlalchemy import and_, or_, not_
from threading import Event
import datetime
import subprocess
import re
import time
import queue
import os
import requests
import json
from bs4 import BeautifulSoup
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from flask import Flask, request, jsonify, after_this_request, render_template
import eventlet
eventlet.monkey_patch()


task_queue = queue.PriorityQueue()
queue_counter = 0


def enqueue_task(priority, message_id):
    global queue_counter
    print(f"+{queue_counter}: priority = {priority}, header_message_id = {message_id}")
    task_queue.put((priority, queue_counter, message_id))
    queue_counter += 1


def process_task(priority, queue_idx, message_id):
    email, reason = get_full_email(message_id)
    if not email:
        print(f"{queue_idx}: Failed to obtain full mail, {reason}")
        return
    summary_data, reason = summarize(email)
    if not summary_data:
        print(f"{queue_idx}: Failed to summarize, {reason}")
        return
    message_summary = database.MessageSummary.from_data(
        summary_data, email['header']['id'])
    status, message, obj = message_summary.add_to_db()
    if not status:
        print(f"{queue_idx}: Failed to add summary to database: {message}")
        return
    print(f"{queue_idx}: Added summary to database successfully")


def process_tasks():
    with app.app_context():
        while True:
            priority, queue_idx, message_id = task_queue.get()
            process_task(priority, queue_idx, message_id)


app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app, origins="*", supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*")
database.init_app(app)

eventlet.spawn(process_tasks)

# Webpages


@app.route('/')
def index():
    return render_template('mailbox.html')

# Socket


thunderbird_clients = set()
frontend_clients = set()


def serialize_datetime(obj):
    """Recursively convert datetime objects in a dictionary to strings."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()

    if isinstance(obj, list):
        return [serialize_datetime(item) for item in obj]

    if isinstance(obj, dict):
        return {key: serialize_datetime(value) for key, value in obj.items()}

    return obj


def message(clients, event, message):
    serialized_message = serialize_datetime(message)
    for sid in clients:
        emit(event, serialized_message, room=sid, namespace='/')


def thunderbridge(event, message):
    message(thunderbird_clients, event, message)


def frontend(event, message):
    message(frontend_clients, event, message)


def message_sync(clients, event, message):
    if not clients:
        return None, "No thunderbridge clients connected"
    response_data = {}
    response_received = Event()

    def handle_client_response(data):
        response_data['value'] = data
        response_received.set()

    serialized_message = serialize_datetime(message)
    for sid in clients:
        emit(event, serialized_message, room=sid,
             namespace='/', callback=handle_client_response)
    response_received.wait(timeout=10)
    if 'value' in response_data:
        return response_data['value'], "Success"
    return None, "All thunderbridge clients didn't return any data"


def thunderbridge_sync(event, message):
    return message_sync(thunderbird_clients, event, message)


def frontend_sync(event, message):
    return message_sync(frontend_clients, event, message)


@socketio.on('connect')
def handle_connect():
    print(f"Client {request.sid} connected!")


@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in thunderbird_clients:
        thunderbird_clients.remove(request.sid)
        frontend_clients.remove(request.sid)
    print()
    print(f'Client {request.sid} disconnected!')


@socketio.on('thunderbridge-hello')
def handle_thunderbridge_hello(message):
    print(f'Thunderbridge {request.sid} connected')
    thunderbird_clients.add(request.sid)
    emit('fetch-emails', {})


@socketio.on('frontend-hello')
def handle_frontend_hello(message):
    print(f'Frontend {request.sid} connected')
    thunderbird_clients.add(request.sid)
    emit('fetch-emails', {})

# APIs


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    if response.status_code == 403:
        print(f"CORS issue detected: {request.url}")
    return response


@app.route('/api/emails', methods=['POST'])
def add_messages():
    data = request.json

    if not data or 'messages' not in data:
        return jsonify({"status": "error", "message": "Expected a 'messages' key in the request data."}), 400

    results = []
    for message_data in data['messages']:
        status, message, obj = database.Message.create_and_add_to_db(
            message_data)
        results.append({"status": status, "message": message})

    if all(result["status"] for result in results):
        return jsonify({"status": "success", "message": "Messages processed successfully.", "details": results}), 200
    else:
        failed_messages = [
            result for result in results if not result["status"]]
        return jsonify({"status": "error", "message": "Some messages could not be processed.", "details": failed_messages}), 400


@app.route('/api/tabs', methods=['GET'])
def get_tabs():
    tab_names = [tab['name'] for tab in settings.TABS]
    tabs = []
    for tab_name in tab_names:
        tab_config = next(
            (item for item in settings.TABS if item['name'] == tab_name), None)
        if not tab_config:
            return jsonify({'error': 'Tab not found'}), 404
        tab_details = {
            'name': tab_config['name'],
            'display_name': tab_config.get('display_name', tab_name)
        }
        tabs.append(tab_details)
    return jsonify(tabs)


@app.route('/api/tabs/<tab>/sections', methods=['GET'])
def get_tab_sections(tab):
    def get_filter_description(section_config, prefix=''):
        filter_descriptions = []
        and_filters = section_config.get('and', [])
        or_filters = section_config.get('or', [])
        not_filters = section_config.get('exclude', [])
        simple_filters = section_config.get('filters', [])

        if and_filters:
            for i, and_filter in enumerate(and_filters, start=1):
                nested_section = next(
                    (sect for sect in settings.SECTIONS if sect['name'] == and_filter), None)
                and_prefix = f'{prefix}AND[{i}] ' if len(
                    and_filters) > 1 else prefix
                filter_descriptions.extend(
                    get_filter_description(nested_section, and_prefix))

        if or_filters:
            for i, or_filter in enumerate(or_filters, start=1):
                nested_section = next(
                    (sect for sect in settings.SECTIONS if sect['name'] == or_filter), None)
                or_prefix = f'{prefix}OR[{i}] ' if len(
                    or_filters) > 1 else prefix
                filter_descriptions.extend(
                    get_filter_description(nested_section, or_prefix))

        if not_filters:
            for i, not_filter in enumerate(not_filters, start=1):
                nested_section = next(
                    (sect for sect in settings.SECTIONS if sect['name'] == not_filter), None)
                not_prefix = f'{prefix}NOT[{i}] '
                filter_descriptions.extend(
                    get_filter_description(nested_section, not_prefix))

        and_prefix = 'AND' if len(simple_filters) > 1 else ''
        for i, simple_filter in enumerate(simple_filters, start=1):
            # Format the simple filter string here
            filter_str = f'{prefix}{and_prefix}[{i}] {simple_filter["type"]}: {simple_filter["value"]}' if and_prefix else f'{prefix}{simple_filter["type"]}: {simple_filter["value"]}'
            filter_descriptions.append(filter_str)

        return filter_descriptions

    tab_config = next(
        (item for item in settings.TABS if item['name'] == tab), None)
    if not tab_config:
        return jsonify({'error': 'Tab not found'}), 404
    section_names = tab_config.get('sections', [])
    sections = []
    for section_name in section_names:
        section_config = next(
            (sect for sect in settings.SECTIONS if sect['name'] == section_name), None)
        if not section_config:
            return jsonify({'error': 'Section not found'}), 404
        section_details = {
            'name': section_name,
            'display_name': section_config.get('display_name', section_name),
            'filters': get_filter_description(section_config),
        }
        sections.append(section_details)
    return jsonify(sections)


@app.route('/api/tabs/<tab>/sections/<section>/emails', methods=['GET'])
def get_emails_by_section(tab, section):
    def get_filters_for_section(section_name):
        section_config = next(
            (sect for sect in settings.SECTIONS if sect['name'] == section_name), None)
        if not section_config:
            raise ValueError(f'Section {section_name} not found')

        query_filters = []

        if 'and' in section_config:
            and_filters = [get_filters_for_section(
                name) for name in section_config['and']]
            query_filters.extend([and_(*section_filters)
                                 for section_filters in and_filters])

        for filter_def in section_config.get('filters', []):
            if filter_def['type'] == 'sender_domain':
                query_filters.append(database.Message.author_email.ilike(
                    f"%@{filter_def['value']}"))
            elif filter_def['type'] == 'sender_email':
                query_filters.append(
                    database.Message.author_email == filter_def['value'])
            elif filter_def['type'] == 'subject_contains':
                query_filters.append(database.Message.subject.ilike(
                    f"%{filter_def['value']}%"))
            elif filter_def['type'] == 'sender_name_contains':
                query_filters.append(database.Message.author_name.ilike(
                    f"%{filter_def['value']}%"))

        # Handle 'or' logic
        if 'or' in section_config:
            or_filters = [get_filters_for_section(
                name) for name in section_config['or']]
            query_filters.append(
                or_(*[and_(*section_filters) for section_filters in or_filters]))

        # Handle 'exclude' logic
        if 'exclude' in section_config:
            exclude_filters = [get_filters_for_section(
                name) for name in section_config['exclude']]
            # Here we need to negate the combined exclude filters
            for exclude_filter in exclude_filters:
                query_filters.append(~and_(*exclude_filter))

        return query_filters

    # Get 'start_from' as a Unix timestamp; default to None if not provided
    start_from = request.args.get('start_from', default=None, type=int)
    limit = request.args.get('limit', default=10, type=int)

    # Find the tab configuration
    tab_config = next(
        (item for item in settings.TABS if item['name'] == tab), None)
    if not tab_config:
        return jsonify({'error': 'Tab not found'}), 404

    # Check if the section exists in the tab configuration
    if section not in tab_config.get('sections', []):
        return jsonify({'error': 'Section not found in tab'}), 404

    # Find the section configuration
    section_config = next(
        (sect for sect in settings.SECTIONS if sect['name'] == section), None)
    if not section_config:
        return jsonify({'error': 'Section not found'}), 404

    # Construct filters for query based on the section configuration
    query_filters = get_filters_for_section(section)

    # Add start_from to the filters if it's provided
    if start_from:
        query_filters.append(database.Message.date <= start_from)

    # Query the database with all the constructed filters and order by date
    messages_query = (database.db.session.query(database.Message)
                      .filter(and_(*query_filters))
                      .order_by(database.Message.date.desc())
                      .limit(limit))

    # Convert the messages to dicts and return JSON
    messages_list = [message.to_dict(relationships=True)
                     for message in messages_query.all()]
    return jsonify(messages_list)


@app.route('/api/enqueue-summary', methods=['POST'])
def enqueue_summary():
    data = request.json
    if not data or not data.get('header_message_id'):
        return jsonify({"error": "Field 'header_message_id' is required and missing."}), 400
    enqueue_task(1000000, data['header_message_id'])
    return jsonify({"status": "Task enqueued successfully"}), 200


@app.route('/api/full-email/<id>', methods=['GET'])
def api_get_full_email(id):
    # Fetch the email header from the database.
    email_header_obj = database.Message.by_header_message_id(id)
    if not email_header_obj:
        return jsonify({"error": "Email header not found"}), 404
    email_header = email_header_obj.to_dict()
    # Use SocketIO to request the email body.
    email_body, reason = thunderbridge_sync('request_email_body', email_header)
    if not email_body:
        return jsonify({"error": f"Email body: {reason}"}), 404
    # Combine the header and body.
    full_email = {
        "header": email_header,
        "body": email_body
    }
    return jsonify(full_email)


@app.route('/api/open-email', methods=['POST'])
def open_email():
    data = request.json
    if not data or not data.get('header_message_id'):
        return jsonify({"error": "Field 'header_message_id' is required and missing."}), 400
    thunderbridge('open-email', data)
    subprocess.run(['open', '-a', 'Thunderbird'], capture_output=False)
    return jsonify({"status": "Message sent to Thunderbird successfully"}), 200


def get_full_email(message_id):
    # Fetch the email header from the database.
    email_header_obj = database.Message.by_header_message_id(message_id)
    if not email_header_obj:
        return None, "Email header not found"
    email_header = email_header_obj.to_dict()
    # Use SocketIO to request the email body.
    email_body, reason = thunderbridge_sync('request_email_body', email_header)
    if not email_body:
        return None, f"Failed to obtain email body - {reason}"
    # Combine the header and body.
    full_email = {
        "header": email_header,
        "body": email_body
    }
    return full_email, "Success"
