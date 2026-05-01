import sys

files = [
    "admin_ui/frontend/src/components/config/ToolForm.tsx",
    "admin_ui/frontend/src/pages/System/ModelsPage.tsx",
    "cli/README.md",
    "docs/Configuration-Reference.md",
    "docs/INSTALLATION.md",
    "docs/MIGRATION.md",
    "docs/ROADMAP.md",
    "docs/contributing/README.md",
    "local_ai_server/Dockerfile",
    "local_ai_server/Dockerfile.gpu",
    "local_ai_server/requirements.txt",
    "src/pipelines/openai.py"
]

for f in files:
    with open(f, "r") as fh:
        content = fh.read()
    
    lines = content.split("\n")
    new_lines = []
    state = "normal" # normal, ours, theirs
    
    for line in lines:
        if line.startswith("<<<<<<< "):
            state = "ours"
        elif line.startswith("======="):
            state = "theirs"
        elif line.startswith(">>>>>>> "):
            state = "normal"
        else:
            if state == "normal" or state == "theirs":
                new_lines.append(line)
                
    with open(f, "w") as fh:
        fh.write("\n".join(new_lines))

print("Conflicts resolved by keeping upstream changes.")
