import os
import threading
import subprocess
import time
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("deepseek_api"),
)

FALLBACK_MODEL = "deepseek/deepseek-v3-base:free"

command_history = []
current_suggestion = ""
suggestion_lock = threading.Lock()
last_request_time = 0

def get_ai_suggestion(user_input, history):
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "Suggest a popular shell command completing the input. Focus on common tools like npm, git, docker, etc., and provide a complete, actionable command. Respond ONLY with the completed command."},
                {"role": "user", "content": f"Complete this command and only respond with the completed command: {user_input}"}
            ],
            max_tokens=20,
            temperature=0.1,
        )
        
        if not completion or not completion.choices:
            return user_input + " "  # Fallback to space
            
        suggestion = completion.choices[0].message.content.strip()
        suggestion = suggestion.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        if not suggestion:  # Empty suggestion
            return user_input + " "
        if suggestion == user_input:  # No extension
            return user_input + " "
        if not suggestion.startswith(user_input):  # Doesn’t match input
            return user_input + suggestion
            
        return suggestion
    except Exception as e:
        print(f"DEBUG: AI suggestion error: {e}")
        return user_input + " "

def fetch_suggestion_async(text, session, request_time):
    global current_suggestion, last_request_time
    
    if len(text.strip()) < 2:
        with suggestion_lock:
            current_suggestion = ""
        return
        
    history = "\n".join(command_history)
    suggestion = get_ai_suggestion(text, history)
    print(f"DEBUG: Input='{text}', Suggestion='{suggestion}'")  # Temporary debuggit
    
    with suggestion_lock:
        if request_time >= last_request_time:
            current_suggestion = suggestion
            if session.app:
                session.app.invalidate()

class AIAutoSuggest(AutoSuggest):
    def get_suggestion(self, _buffer, document):
        typed_text = document.text
        if not typed_text.strip():
            return None
        with suggestion_lock:
            suggestion = current_suggestion
        if suggestion and suggestion.startswith(typed_text):
            return Suggestion(suggestion[len(typed_text):])
        return None

def main():
    style = Style.from_dict({
        'prompt': '#00aa00 bold',  # Green prompt
        'suggestion': 'bg:#ffff00 #000000 bold',  # Yellow suggestion on black
    })
    session = PromptSession(auto_suggest=AIAutoSuggest(), style=style)
    bindings = KeyBindings()

    @bindings.add("tab")
    def _(event):
        buff = event.app.current_buffer
        if buff.suggestion:
            buff.insert_text(buff.suggestion.text)

    @bindings.add("c-c")
    def _(event):
        event.app.exit(result=None)
        raise KeyboardInterrupt()

    last_fetch_time = 0
    min_delay_between_fetches = 0.2
    
    def on_text_changed(_):
        nonlocal last_fetch_time
        global last_request_time
        current_time = time.time()
        
        if current_time - last_fetch_time < min_delay_between_fetches:
            return
            
        last_fetch_time = current_time
        last_request_time = current_time
        buffer_text = session.default_buffer.document.text
        
        if len(buffer_text.strip()) < 2:
            return
            
        threading.Thread(target=fetch_suggestion_async, args=(buffer_text, session, current_time), daemon=True).start()

    session.default_buffer.on_text_changed += on_text_changed

    print("=== AI Shell ===")
    print("Type commands, press TAB to complete suggestions")
    
    while True:
        try:
            message = HTML('<prompt>$ </prompt>')
            user_input = session.prompt(message, key_bindings=bindings)
            if user_input is None:
                continue
            user_cmd = user_input.strip().lower()

            if user_cmd in ("exit", "quit"):
                break

            command_history.append(user_input)
            with suggestion_lock:
                current_suggestion = ""
            run_in_terminal(lambda: subprocess.run(user_input, shell=True))
        except KeyboardInterrupt:
            print("\nUse 'exit' or 'quit' to exit")
            continue
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()