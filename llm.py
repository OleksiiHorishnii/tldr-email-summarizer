import json
import requests
from jsonschema import validate, ValidationError
import eventlet.semaphore

import settings

ollama_lock = eventlet.semaphore.Semaphore()


def ollama(model, prompt):
    with ollama_lock:
        try:
            response = requests.post('http://localhost:11434/api/generate',
                                     json={
                                         'model': model,
                                         'prompt': prompt,
                                         'stream': False
                                     })
            # Check if the HTTP request was successful
            if response.status_code != 200:
                return None, f"Failed to generate response. HTTP status: {response.status_code}. Message: {response.text}"
            # Check if the 'response' key exists in the returned JSON
            json_data = response.json()
            if 'response' not in json_data:
                return None, "Unexpected response format. 'response' key missing."
            return json_data['response'], "Success"
        except requests.RequestException as e:
            return None, "An error occurred during the request: {e}"
        except Exception as e:
            return None, f"An unexpected error occurred: {e}"


def extract_json_string(text):
    if not isinstance(text, str):
        return None, "Provided text is not a string."

    start_idx = text.find('{')
    end_idx = text.rfind('}')

    if start_idx == -1 or end_idx == -1:
        return None, "Cannot find JSON object in the provided text."

    # Extract the JSON string
    return text[start_idx:end_idx + 1], None


def prompt_and_validate(prompt, prompting_function, json_checks, print_fn, max_retries=3):
    for _ in range(max_retries):
        # Get the prompt result from the prompting function
        prompt_result, reason = prompting_function(prompt)
        if prompt_result is None:
            print_fn(reason)
            continue
        print_fn("from llm: " + prompt_result)
        # Extract the JSON string from the result
        json_string, reason = extract_json_string(prompt_result)
        if json_string is None:
            print_fn(reason)
            continue
        try:
            # Attempt to transform the result into JSON
            parsed_json = json.loads(json_string)
            # Validate the JSON
            validate(instance=parsed_json, schema=json_checks)
            # prints the created ticket details
            print_fn("valid result:\n" + json.dumps(parsed_json, indent=4))
            return parsed_json, "Success"  # Return the valid JSON
        except ValidationError as e:
            # Handle issues related to JSON parsing
            print_fn(f"Data is invalid! Reason: {e.message}")
    # If we've exceeded the max retries
    return None, "Exceeded maximum retries without obtaining a valid input."


def llm(prompt, print_fn=print):
    def prompting_function(prompt):
        return ollama(settings.MODEL_NAME, prompt)
    return prompt_and_validate(prompt,
                               prompting_function,
                               settings.FIELD_CHECKS,
                               print_fn,
                               max_retries=settings.MAX_RETRIES)
