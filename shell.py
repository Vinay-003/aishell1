import os
import threading
import subprocess
import time
import json
import glob
import re
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI, APIConnectionError
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from dotenv import load_dotenv

load_dotenv()

# At the top of your file, add this debug print
print("Using OpenRouter API key:", os.getenv("deepseek_api")[:8] + "..." if os.getenv("deepseek_api") else "Not found")

FALLBACK_MODEL = "openai/gpt-3.5-turbo:free"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("deepseek_api"),
    timeout=5.0,
    default_headers={
        "HTTP-Referer": "https://openrouter.ai/",  # Required for OpenRouter
    }
)

# Test the API connection
def test_api_connection():
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'API connection successful'"}
            ],
            max_tokens=10
        )
        print("API Test Response:", completion.choices[0].message.content if completion.choices else "No response")
        return True
    except Exception as e:
        print("API Test Error:", str(e))
        return False

# Call this at startup
if test_api_connection():
    print("OpenRouter API connection successful")
else:
    print("OpenRouter API connection failed")

#something 


# Global state management
command_history = []
current_suggestion = ""
suggestion_lock = threading.Lock()
last_request_time = 0

def get_ai_suggestion(user_input):
    """Get command completion suggestions from the AI model."""
    try:
        if len(user_input.strip()) < 3:
            return ""

        # print(f"Requesting suggestion for: {user_input}")  # Debug print
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a command-line expert. Complete the given command. Respond ONLY with the completed command, no explanations. Focus on common commands like git, docker, npm, pip, cat, touch, sudo, ls, cd, mkdir, rm, cp, mv, pwd, echo, grep, chmod, chown, ps, kill, top, man, whoami, ifconfig, ping, curl, wget, tar, unzip, zip, ssh, scp, find, history, clear, alias, df, du, nano, vi, apt, yum, dnf, pacman, service, systemctl, hostname, env, export, date, time, python, node, java, javac, gcc, make, htop, tmux, screen, netstat, traceroute, dig, npm, npx, pip3, virtualenv, conda, which, whereis, uname, lsb_release  etc . look out for other commands too",
                },
                {
                    "role": "user", 
                    "content": f"Complete this command: {user_input}"
                }
            ],
            max_tokens=50,
            temperature=0.1
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
        
        # print(f"Got suggestion: {suggestion}")  # Debug print
        return suggestion
        
    except Exception as e:
        print(f"[Error] AI suggestion failed: {str(e)}")
        return ""

def get_shell_command(query):
    """Convert natural language query to shell command"""
    try:
        # print(f"Sending query to AI: {query}")  # Debug print
        completion = client.chat.completions.create(
            model="openai/gpt-3.5-turbo:free",
            messages=[
                {
                    "role": "system", 
                    "content": """You are a command-line expert. Convert natural language queries into appropriate shell commands.
                    For file operations, prefer simple commands like touch, echo, mkdir, etc.
                    Respond ONLY with the command, no explanations or additional text."""
                },
                {
                    "role": "user", 
                    "content": f"Convert this to a shell command: {query}"
                }
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        if not completion or not completion.choices:
            print(f"API Response: {completion}")  # Debug print
            return None
            
        command = completion.choices[0].message.content.strip()
        command = command.split("\n")[0].split("#")[0].strip().strip('"').strip("'")
        
        print(f"Generated command: {command}")  # Debug print
        return command
        
    except Exception as e:
        print(f"Error in get_shell_command: {type(e).__name__}: {str(e)}")
        return None
def fetch_suggestion_async(text, session):
    """Fetch suggestions asynchronously to avoid blocking the UI."""
    global current_suggestion
    
    if len(text.strip()) < 2:
        with suggestion_lock:
            current_suggestion = ""
        return
        
    suggestion = get_ai_suggestion(text)
    
    with suggestion_lock:
        current_suggestion = suggestion
    
    # Force a refresh of the UI
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
            
        if suggestion and suggestion.startswith(typed_text) and suggestion != typed_text:
            return Suggestion(suggestion[len(typed_text):])
        return None

def execute_command(command):
    try:
        # Basic git repository check
        if command.startswith('git') and command != 'git --version':
            try:
                subprocess.run(['git', 'rev-parse', '--git-dir'], 
                             check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                print("Error: Not a git repository")
                return False

        # Execute the command
        result = subprocess.run(command, shell=True, check=True, text=True, 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.stdout:
            print(result.stdout)
        return True
        #something changed
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(f"Error: {e.stderr}")
        else:
            print(f"Command failed with exit code {e.returncode}")
        return False

class ProjectAnalyzer:
    """Analyzes project structure and dependencies across different project types"""
    
    KNOWN_CONFIG_FILES = {
        'python': ['requirements.txt', 'Pipfile', 'pyproject.toml', 'setup.py'],
        'node': ['package.json', 'package-lock.json', 'yarn.lock'],
        'java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
        'ruby': ['Gemfile', 'Gemfile.lock'],
        'php': ['composer.json', 'composer.lock'],
        'rust': ['Cargo.toml', 'Cargo.lock'],
        'go': ['go.mod', 'go.sum']
    }

    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir)
        self.project_type = None
        self.config_files = {}
        self.source_files = {}
        
    def scan_project(self) -> Dict:
        """Scan project directory and identify project type and structure"""
        self._find_config_files()
        self._find_source_files()
        self._determine_project_type()
        
        return {
            "project_type": self.project_type,
            "config_files": self.config_files,
            "source_files": self.source_files,
            "dependencies": self._get_dependencies()
        }
        
    def _find_config_files(self):
        """Find all known configuration files"""
        for lang, files in self.KNOWN_CONFIG_FILES.items():
            found_files = {}
            for file in files:
                path = self.root_dir / file
                if path.exists():
                    try:
                        with open(path, 'r') as f:
                            found_files[file] = f.read()
                    except Exception:
                        found_files[file] = None
            if found_files:
                self.config_files[lang] = found_files

    def _find_source_files(self):
        """Find source files for different languages"""
        extensions = {
            'python': ['*.py'],
            'node': ['*.js', '*.jsx', '*.ts', '*.tsx'],
            'java': ['*.java'],
            'ruby': ['*.rb'],
            'php': ['*.php'],
            'rust': ['*.rs'],
            'go': ['*.go'],
            'html': ['*.html', '*.htm'],
            'css': ['*.css', '*.scss', '*.sass', '*.less'],
        }
        
        for lang, exts in extensions.items():
            files = []
            for ext in exts:
                files.extend([str(p) for p in self.root_dir.rglob(ext)])
            if files:
                self.source_files[lang] = files

    def _determine_project_type(self):
        """Determine primary project type based on config files and source files"""
        if not self.config_files and not self.source_files:
            return
            
        # First check config files
        for lang in self.config_files:
            self.project_type = lang
            break
            
        # If no config files, check source files
        if not self.project_type and self.source_files:
            # Choose the language with most source files
            self.project_type = max(self.source_files.items(), key=lambda x: len(x[1]))[0]

    def _get_dependencies(self) -> Dict:
        """Extract dependencies from config files"""
        deps = {}
        
        if 'python' in self.config_files:
            if 'requirements.txt' in self.config_files['python']:
                deps['python'] = self._parse_requirements_txt(self.config_files['python']['requirements.txt'])
                
        if 'node' in self.config_files:
            if 'package.json' in self.config_files['node']:
                try:
                    package_json = json.loads(self.config_files['node']['package.json'])
                    deps['node'] = {
                        'dependencies': package_json.get('dependencies', {}),
                        'devDependencies': package_json.get('devDependencies', {})
                    }
                except json.JSONDecodeError:
                    pass
                    
        return deps

    @staticmethod
    def _parse_requirements_txt(content: str) -> List[str]:
        """Parse requirements.txt content"""
        return [line.strip() for line in content.splitlines() 
                if line.strip() and not line.startswith('#')]

def analyze_error(error_message: str) -> Dict:
    """Analyze error message using AI and project context"""
    # If it's a ModuleNotFoundError, handle it directly
    if "ModuleNotFoundError: No module named" in error_message:
        # Extract the module name from the error message
        module_name = error_message.split("'")[1]
        return {
            "error_type": "import_error",
            "project_type": "python",
            "missing_dependencies": [module_name],
            "commands": [f"pip install {module_name}"],
            "explanation": f"The Python package '{module_name}' is not installed",
            "file_changes": []
        }
    
    # For other errors, try AI analysis
    project_analyzer = ProjectAnalyzer()
    project_info = project_analyzer.scan_project()
    
    try:
        completion = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """You are a development troubleshooter. Analyze the error message and suggest fixes.
                    Return a valid JSON object with this exact structure:
                    {
                        "error_type": "import_error",
                        "project_type": "python",
                        "missing_dependencies": ["package_name"],
                        "commands": ["pip install package_name"],
                        "explanation": "Package X is not installed",
                        "file_changes": []
                    }"""
                },
                {
                    "role": "user",
                    "content": f"Error message: {error_message}\nProject info: {json.dumps(project_info)}"
                }
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        response = completion.choices[0].message.content
        return json.loads(response)
        
    except Exception as e:
        print(f"Error analysis failed: {str(e)}")
        # Provide a meaningful fallback for ModuleNotFoundError
        if "ModuleNotFoundError" in error_message:
            return {
                "error_type": "import_error",
                "project_type": "python",
                "missing_dependencies": ["pandas"],
                "commands": ["pip install pandas"],
                "explanation": "The pandas package is not installed",
                "file_changes": []
            }
        return {
            "error_type": "unknown",
            "project_type": "python",
            "missing_dependencies": [],
            "commands": [],
            "explanation": "Could not analyze error",
            "file_changes": []
        }

def apply_fixes(analysis: Dict) -> bool:
    """Apply the suggested fixes"""
    if not analysis:
        return False
        
    print("\nSuggested fixes:")
    print(f"Error type: {analysis['error_type']}")
    print(f"Project type: {analysis['project_type']}")
    
    if analysis.get('missing_dependencies'):
        print("\nMissing dependencies:")
        for dep in analysis['missing_dependencies']:
            print(f"  - {dep}")
            
    if analysis.get('commands'):
        print("\nProposed commands:")
        for cmd in analysis['commands']:
            print(f"  - {cmd}")
            
    if analysis.get('file_changes'):
        print("\nRequired file changes:")
        for change in analysis['file_changes']:
            print(f"  - {change['file']}: {change['changes']}")
            
    print(f"\nExplanation: {analysis['explanation']}")
    
    # First ask for overall confirmation
    confirm = input("\nWould you like to proceed with the fixes? [y/N] ")
    if confirm.lower() != 'y':
        return False
        
    success = True
    
    # Execute commands with individual confirmations
    for cmd in analysis.get('commands', []):
        print(f"\nCommand: {cmd}")
        cmd_confirm = input("Execute this command? [y/N] ")
        
        if cmd_confirm.lower() == 'y':
            try:
                print(f"Executing: {cmd}")
                result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
                if result.stdout:
                    print(result.stdout)
            except subprocess.CalledProcessError as e:
                print(f"Command failed: {e}")
                if e.stderr:
                    print(f"Error output: {e.stderr}")
                success = False
                
                # Ask if user wants to continue after a failure
                continue_confirm = input("Command failed. Continue with remaining commands? [y/N] ")
                if continue_confirm.lower() != 'y':
                    break
        else:
            print(f"Skipping command: {cmd}")
            
    if success:
        print("\nAll selected fixes have been applied successfully.")
    else:
        print("\nSome fixes were not applied successfully. Please check the output above.")
        
    return success

def main():
    style = Style.from_dict({
        'prompt': '#00aa00 bold',  # Green prompt
        'suggestion': '#666666 italic',  # Gray suggestions
    })
    
    session = PromptSession(
        auto_suggest=AIAutoSuggest(),
        style=style,
        complete_while_typing=True,
        complete_in_thread=True
    )
    
    bindings = KeyBindings()

    @bindings.add("tab")
    @bindings.add("right")
    def _(event):
        buff = event.app.current_buffer
        if buff.suggestion:
            buff.insert_text(buff.suggestion.text)

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
        
        if buffer_text.startswith("?") or len(buffer_text.strip()) < 2:
            return
            
        threading.Thread(
            target=fetch_suggestion_async,
            args=(buffer_text, session),
            daemon=True
        ).start()

    session.default_buffer.on_text_changed += on_text_changed

    print("=== AI Shell ===")
    print("Type commands directly or start with ? for natural language (e.g., ?how to list all files)")
    print("Press TAB or RIGHT ARROW to complete suggestions, ENTER to execute")
    
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

            # Handle error analysis
            if user_input.startswith("!error"):
                error_msg = user_input[6:].strip()
                if not error_msg:
                    print("Usage: !error <paste error message>")
                    continue
                    
                print("\nAnalyzing error...")
                analysis = analyze_error(error_msg)
                if analysis:
                    apply_fixes(analysis)
                continue

            if user_input.startswith("?"):
                query = user_input[1:].strip()
                if not query:
                    print("Please provide a query after ?")
                    continue
                    
                print("Translating query...")
                try:
                    command = get_shell_command(query)
                    if not command:
                        print("Could not generate a command for your query. Please try rephrasing it.")
                        continue
                        
                    # print(f"Suggested command: {command}")
                    confirm = session.prompt("Execute this command? [y/N] ")
                    if confirm.lower() != 'y':
                        continue
                    user_input = command
                except Exception as e:
                    print(f"Error processing query: {str(e)}")
                    continue

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
