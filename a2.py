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

# Initialize OpenAI client with OpenRouter endpoint
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("deepseek_api"),
)

FALLBACK_MODEL = "openai/gpt-3.5-turbo:free"

# Global state management
command_history = []
current_suggestion = ""
suggestion_lock = threading.Lock()

def get_ai_suggestion(user_input, history):
    """Get command completion suggestions from the AI model."""
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful AI that completes bash commands. Respond ONLY with the completed command, no explanations."},
                {"role": "user", "content": f"Complete this command: {user_input}"}
            ],
            max_tokens=20,
            temperature=0.1,
        )
        
        if not completion or not completion.choices:
            return ""
            
        suggestion = completion.choices[0].message.content.strip()
        suggestion = suggestion.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        # Ensure suggestion starts with user input
        if suggestion and not suggestion.startswith(user_input):
            suggestion = user_input + suggestion
        elif suggestion == user_input:
            suggestion += " "
            
        return suggestion
        
    except Exception as e:
        print(f"[Error] AI suggestion failed: {str(e)}")
        return ""

def fetch_suggestion_async(text, session):
    """Fetch suggestions asynchronously to avoid blocking the UI."""
    global current_suggestion
    
    if len(text.strip()) < 2:
        with suggestion_lock:
            current_suggestion = ""
        return
        
    history = "\n".join(command_history)
    suggestion = get_ai_suggestion(text, history)
    
    with suggestion_lock:
        current_suggestion = suggestion
    
    if session.app:
        session.app.invalidate()

class AIAutoSuggest(AutoSuggest):
    """Custom AutoSuggest class for AI-powered command completion."""
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
    """Main application entry point."""
    # Configure prompt session with styling
    style = Style.from_dict({
        'prompt': '#00aa00 bold',  # Green prompt
        'suggestion': '#666666 italic',  # Gray suggestions
    })
    session = PromptSession(auto_suggest=AIAutoSuggest(), style=style)
    bindings = KeyBindings()

    # Key bindings for accepting suggestions
    @bindings.add("tab")
    @bindings.add("right")
    def _(event):
        buff = event.app.current_buffer
        if buff.suggestion:
            buff.insert_text(buff.suggestion.text)

    # Handle Ctrl+C gracefully
    @bindings.add("c-c")
    def _(event):
        event.app.exit(result=None)
        raise KeyboardInterrupt()

    # Debounce suggestion requests
    last_fetch_time = 0
    min_delay_between_fetches = 0.3  # 300ms minimum delay between fetches
    
    def on_text_changed(_):
        nonlocal last_fetch_time
        current_time = time.time()
        
        if current_time - last_fetch_time < min_delay_between_fetches:
            return
            
        last_fetch_time = current_time
        buffer_text = session.default_buffer.document.text
        
        if len(buffer_text.strip()) < 2:
            return
            
        threading.Thread(target=fetch_suggestion_async, args=(buffer_text, session), daemon=True).start()

    session.default_buffer.on_text_changed += on_text_changed

    # Main interaction loop
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
                global current_suggestion
                current_suggestion = ""
            run_in_terminal(lambda: subprocess.run(user_input, shell=True))
            
        except KeyboardInterrupt:
            continue
        except Exception as e:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
