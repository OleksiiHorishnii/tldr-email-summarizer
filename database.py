from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from datetime import datetime
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.collections import InstrumentedList
import re

db = SQLAlchemy()


def init_app(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////Users/oleksiihorishnii/.llm-mail-summarizer/database.db'
    # You might want to add this to suppress a warning
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()


def add_unique_item_to_db(model, unique_field_names, **kwargs):
    """Add or update an item in the database based on unique criteria.

    :param model: SQLAlchemy model class
    :param unique_field_names: List of unique field names to filter by
    :param kwargs: Attributes for creating a new model instance or updating an existing one
    :return: tuple (status: bool, message: str, item: model instance)
    """

    # Construct the dictionary of unique attributes
    unique_fields = {field: kwargs[field] for field in unique_field_names}

    # Query the DB to check if an item with the same unique attributes exists
    existing_item = db.session.query(model).filter_by(**unique_fields).first()

    if existing_item:
        # Update the existing item's attributes
        for key, value in kwargs.items():
            setattr(existing_item, key, value)
        message = f"{model.__name__} updated successfully."
        item_to_return = existing_item
    else:
        new_item = model(**kwargs)
        db.session.add(new_item)
        message = f"{model.__name__} added successfully."
        item_to_return = new_item

    try:
        db.session.commit()
        return True, message, item_to_return
    except IntegrityError as e:
        db.session.rollback()
        print(str(e))
        return False, f"Database integrity error occurred while processing {model.__name__}.", None


def split_email_handle(full_string):
    match = re.match(
        r'(?:"?([^"<]+)"?\s)?<?([^<>@\s]+@[^<>@\s]+)>?', full_string.strip())
    if match:
        name, email = match.groups()
        name = name.strip().strip('"') if name else None
        return name, email
    return None, full_string

# Classes


class BaseMixin:
    def to_dict(self, relationships=False):
        # Columns
        columns = [c.key for c in inspect(self).mapper.column_attrs]
        data = {col: getattr(self, col) for col in columns}
        if relationships:
            relationships = inspect(self).mapper.relationships
            for rel in relationships:
                value = getattr(self, rel.key)
                if value is None:
                    data[rel.key] = None
                # For lists (e.g., one-to-many relationships)
                elif isinstance(value, InstrumentedList):
                    data[rel.key] = [item.to_dict() for item in value]
                # For single objects (e.g., many-to-one relationships)
                elif isinstance(value, InstrumentedAttribute):
                    data[rel.key] = value.to_dict()
                elif isinstance(value, BaseMixin):
                    data[rel.key] = value.to_dict()
                else:
                    data[rel.key] = str(value)
        return data

    def add_to_db(self):
        # This should be implemented in each child model
        unique_fields = self.unique_fields()
        item_data = self.to_dict()
        if 'id' in item_data:
            del item_data['id']
        return add_unique_item_to_db(self.__class__, unique_fields, **item_data)

    def unique_fields(self):
        """To be overridden in child models to return the unique fields."""
        raise NotImplementedError(
            "unique_fields method needs to be implemented in child models.")


class Account(db.Model, BaseMixin):
    # Auto-incremented ID for internal use
    id = db.Column(db.Integer, primary_key=True)
    tb_id = db.Column(db.String, unique=True, nullable=False)  # Thunderbird ID
    # The human-friendly name of this account.
    name = db.Column(db.String, nullable=False)
    # What sort of account this is, e.g. imap, nntp, or pop3.
    type = db.Column(db.String, nullable=False)
    # Relationships
    folders = db.relationship('Folder', backref='account', lazy='dynamic')
    identities = db.relationship('Identity', backref='account', lazy='dynamic')

    def unique_fields(self):
        return ["tb_id"]


class Folder(db.Model, BaseMixin):
    id = db.Column(db.Integer, primary_key=True)  # Auto-incremented ID
    accountId = db.Column(db.String, db.ForeignKey(
        'account.tb_id'), nullable=False)
    # Path to this folder in the account.
    path = db.Column(db.String, nullable=False)
    # The human-friendly name of this folder.
    name = db.Column(db.String, nullable=False)
    # The type of folder, e.g. inbox, drafts, etc.
    type = db.Column(db.String, nullable=False)
    # Relationships
    messages = db.relationship('Message', backref='folder', lazy='dynamic')

    @classmethod
    def from_data(cls, data):
        """Creates a Folder instance from a given data."""
        return cls(
            accountId=data['accountId'],
            path=data['path'],
            name=data.get('name', ""),
            type=data.get('type', "")
        )

    def unique_fields(self):
        return ["accountId", "path"]


class Identity(db.Model, BaseMixin):
    # Auto-incremented ID for internal use
    id = db.Column(db.Integer, primary_key=True)
    accountId = db.Column(db.String, db.ForeignKey(
        'account.tb_id'), nullable=False)
    composeHtml = db.Column(db.Boolean)
    email = db.Column(db.String, nullable=False)
    label = db.Column(db.String)
    name = db.Column(db.String, nullable=False)
    organization = db.Column(db.String)
    replyTo = db.Column(db.String)
    signature = db.Column(db.String)
    signatureIsPlainText = db.Column(db.Boolean)

    def unique_fields(self):
        return ["accountId", "email"]


class Message(db.Model, BaseMixin):
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey(
        'folder.id'), nullable=False)
    header_message_id = db.Column(db.String, unique=True, nullable=False)
    date = db.Column(db.Integer, nullable=False)  # Unix timestamp
    author_name = db.Column(db.String, nullable=True)
    author_email = db.Column(db.String, nullable=False)
    subject = db.Column(db.String, nullable=True)
    read = db.Column(db.Boolean, default=False)
    new = db.Column(db.Boolean, default=False)
    headers_only = db.Column(db.Boolean, default=False)
    flagged = db.Column(db.Boolean, default=False)
    junk = db.Column(db.Boolean, default=False)
    junk_score = db.Column(db.Integer, default=0)
    size = db.Column(db.Integer, nullable=True)
    external = db.Column(db.Boolean, default=False)
    # Relationships
    recipients = db.relationship('Recipient', backref='message', lazy=True)
    tags = db.relationship('Tag', backref='message', lazy=True)

    @classmethod
    def from_data(cls, data):
        """Creates a Message instance from a given data."""
        date_object = datetime.fromisoformat(
            data['date'].replace("Z", "+00:00"))
        unix_timestamp = int(date_object.timestamp())
        author_name, author_email = split_email_handle(data['author'])
        return cls(
            header_message_id=data.get("headerMessageId", ""),
            date=unix_timestamp,
            author_name=author_name,
            author_email=author_email,
            subject=data.get('subject', ""),
            read=data.get('read', False),
            new=data.get('new', False),
            headers_only=data.get('headers_only', False),
            flagged=data.get('flagged', False),
            junk=data.get('junk', False),
            junk_score=data.get('junk_score', 0),
            size=data.get('size', None),
            external=data.get('external', False)
        )

    @classmethod
    def create_and_add_to_db(cls, data):
        folder = Folder.from_data(data['folder'])
        folder_status, folder_message, folder = folder.add_to_db()
        # If folder addition was successful or folder already exists, proceed
        if folder_status:
            message = cls.from_data(data)
            message.folder_id = folder.id
            return message.add_to_db()
        return False, folder_message, None

    @classmethod
    def by_header_message_id(cls, header_message_id):
        message = Message.query.filter_by(
            header_message_id=header_message_id).first()
        return message

    def unique_fields(self):
        return ["header_message_id"]


class MessageSummary(db.Model, BaseMixin):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey(
        'message.id'), nullable=False)  # Assuming you have a Message model
    summary = db.Column(db.String)
    isWork = db.Column(db.Float)
    isCommerce = db.Column(db.Float)
    isSpam = db.Column(db.Float)

    # Relationship
    message = db.relationship(
        'Message', backref=db.backref('summary', uselist=False))

    @classmethod
    def from_data(cls, data, message_id):
        """Creates a Message instance from a given data."""
        return cls(
            message_id=message_id,
            summary=data.get('summary', ''),
            isWork=data['isWork'],
            isCommerce=data['isCommerce'],
            isSpam=data['isSpam']
        )

    def unique_fields(self):
        return ["message_id"]


class Recipient(db.Model, BaseMixin):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey(
        'message.id'), nullable=False)
    email = db.Column(db.String, nullable=False)

    def unique_fields(self):
        return ["message_id", "email"]


class Tag(db.Model, BaseMixin):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey(
        'message.id'), nullable=False)
    tag = db.Column(db.String, nullable=False)

    def unique_fields(self):
        return ["message_id", "tag"]

# Indexing


Index('index_read_date', Message.date, Message.read)
Index('index_flagged_date', Message.date, Message.flagged)
