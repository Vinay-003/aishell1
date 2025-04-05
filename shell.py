import os
import threading
import subprocess
import time
from openai import OpenAI, APIConnectionError
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("deepseek_api"),
    timeout=5.0
)

FALLBACK_MODEL = "openai/gpt-3.5-turbo:free"

command_history = []
current_suggestion = ""
suggestion_lock = threading.Lock()
last_request_time = 0

def get_ai_suggestion(user_input):
    try:
        if len(user_input.strip()) < 3:
            return None

        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "Complete this shell command. ONE-LINE response."},
                {"role": "user", "content": f"Complete: {user_input}"}
            ],
            max_tokens=10,
            temperature=0.1,
        )
        
        if not completion or not completion.choices:
            return None
            
        suggestion = completion.choices[0].message.content.strip()
        suggestion = suggestion.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        if not suggestion or suggestion == user_input:
            return None
        if not suggestion.startswith(user_input):
            return user_input + suggestion
            
        return suggestion
    except (APIConnectionError, Exception):
        return None

def get_shell_command(query):
    """Convert natural language query to shell command"""
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "Convert natural language to a shell command. Respond ONLY with the command, no explanations."},
                {"role": "user", "content": query}
            ],
            max_tokens=50,
            temperature=0.1,
        )
        
        if not completion or not completion.choices:
            return None
            
        command = completion.choices[0].message.content.strip()
        command = command.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        return command
    except (APIConnectionError, Exception):
        return None

class AIAutoSuggest(AutoSuggest):
    def get_suggestion(self, _buffer, document):
        global current_suggestion
        typed_text = document.text
        
        if not typed_text.strip() or typed_text.startswith("?"):
            return None
            
        with suggestion_lock:
            suggestion = current_suggestion
            
        if suggestion and suggestion.startswith(typed_text):
            return Suggestion(suggestion[len(typed_text):])
        return None

def execute_command(command):
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(f"Error: {e.stderr}")
        else:
            print(f"Command failed with exit code {e.returncode}")
        return False

def main():
    style = Style.from_dict({
        'prompt': '#00aa00 bold',
        'command': '#0000ff bold',
    })
    
    session = PromptSession(
        auto_suggest=AIAutoSuggest(),
        style=style,
        complete_while_typing=True
    )
    
    bindings = KeyBindings()

    @bindings.add("tab")
    def _(event):
        buff = event.app.current_buffer
        if buff.suggestion:
            buff.insert_text(buff.suggestion.text)

    @bindings.add("enter")
    def _(event):
        buff = event.app.current_buffer
        text = buff.text.strip()
        if text:  # Only accept if there's actual text
            event.app.exit(result=text)

    @bindings.add("c-c")
    def _(event):
        event.app.exit(result=None)
        raise KeyboardInterrupt()

    def update_suggestion(text):
        global current_suggestion, last_request_time
        suggestion = get_ai_suggestion(text)
        if suggestion:
            with suggestion_lock:
                current_suggestion = suggestion

    def on_text_changed(_):
        buffer_text = session.default_buffer.document.text
        if len(buffer_text.strip()) < 3 or buffer_text.startswith("?"):
            with suggestion_lock:
                global current_suggestion
                current_suggestion = ""
            return
            
        threading.Thread(
            target=update_suggestion,
            args=(buffer_text,),
            daemon=True
        ).start()

    session.default_buffer.on_text_changed += on_text_changed

    print("=== AI Shell ===")
    print("Type commands directly or start with ? for natural language (e.g., ?how to list all files)")
    print("Press TAB to complete suggestions, ENTER to execute")
    
    while True:
        try:
            message = HTML('<prompt>$ </prompt>')
            user_input = session.prompt(message, key_bindings=bindings)
            
            if user_input is None:
                continue
                
            user_input = user_input.strip()
            if not user_input:
                continue
                
            if user_input.lower() in ("exit", "quit"):
                break

            if user_input.startswith("?"):
                query = user_input[1:].strip()
                if not query:
                    print("Please provide a query after ?")
                    continue
                    
                print("Translating query...")
                command = get_shell_command(query)
                if not command:
                    print("Failed to translate query")
                    continue
                    
                print(f"Suggested command: {command}")
                confirm = session.prompt("Execute this command? [y/N] ")
                if confirm.lower() != 'y':
                    continue
                user_input = command

            command_history.append(user_input)
            with suggestion_lock:
                current_suggestion = ""
            
            execute_command(user_input)
            
        except KeyboardInterrupt:
            print("\nUse 'exit' or 'quit' to exit")
            continue
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
