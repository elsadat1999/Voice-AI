import os

files_to_update = [
    "docker-compose.yml",
    "docker-compose.gpu.yml",
    ".env",
    ".env.example",
    "Makefile"
]

replacements = {
    "Asterisk-AI-Voice-Agent": "Voice-AI",
    "Asterisk AI Voice Agent": "Voice-AI",
    "Asterisk AI": "Voice-AI",
    "AAVA": "Voice-AI",
    "AVA-AI-Voice-Agent-for-Asterisk": "Voice-AI-for-Asterisk",
    "COMPOSE_PROJECT_NAME=aava": "COMPOSE_PROJECT_NAME=voice-ai",
    "COMPOSE_PROJECT_NAME=asterisk-ai-voice-agent": "COMPOSE_PROJECT_NAME=voice-ai",
    "HOST_PROJECT_ROOT=/root/Asterisk-AI-Voice-Agent": "HOST_PROJECT_ROOT=/root/Voice-AI",
    "HOST_PROJECT_ROOT=/root/Asterisk-Agent-Develop": "HOST_PROJECT_ROOT=/root/Voice-AI"
}

for filepath in files_to_update:
    full_path = os.path.join("/Users/memohamed/Desktop/Products/AVA-AI-Voice-Agent-for-Asterisk", filepath)
    if not os.path.exists(full_path):
        print(f"Skipping {filepath}, not found")
        continue
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    for old_str, new_str in replacements.items():
        content = content.replace(old_str, new_str)
        
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

print("Replacement complete in root configs.")