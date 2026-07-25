import subprocess
import os

def escape_typst(text: str) -> str:
    if not text:
        return ""
    # We will test escaping various characters
    for char in ['\\', '*', '_', '$', '<', '>', '@', '[', ']', '#']:
        text = text.replace(char, '\\' + char)
    return text

basics = {'name': 'Test <User>', 'location': '=Loc+', 'phone': '123', 'email': 'a@b', 'linkedin': 'C++', 'github': '#git'}
summary = "= Summary with C++ and - bullets and + and = at start"
experience = [{'company': 'Comp > <', 'start_date': '2020', 'end_date': '2021', 'position': 'Dev', 'location': 'Remote', 'highlights': ['= Revenue up 10%', '+ Added C++', '- reduced bugs']}]

typst_code = f"""
#set document(title: "{escape_typst(basics.get('name', 'Resume'))}")
#set page(margin: (x: 0.9in, y: 0.9in))
#set text(size: 11pt)

#show heading: it => [
  #set text(size: 11pt, weight: "regular")
  #block(smallcaps(it.body))
  #v(-0.2em)
  #line(length: 100%, stroke: 0.5pt)
  #v(0.1em)
]

#align(center)[
  #text(16pt, weight: "bold")[{escape_typst(basics.get('name', ''))}]
  
  {escape_typst(basics.get('location', ''))} | {escape_typst(basics.get('phone', ''))} | {escape_typst(basics.get('email', ''))}
  
  {escape_typst(basics.get('linkedin', ''))} | {escape_typst(basics.get('github', ''))}
]

= Summary
{escape_typst(summary)}

= Experience
"""
for exp in experience:
    typst_code += f"""
*{escape_typst(exp.get('company', ''))}* #h(1fr) {escape_typst(exp.get('start_date', ''))} - {escape_typst(exp.get('end_date', ''))} \\
_{escape_typst(exp.get('position', ''))}_, {escape_typst(exp.get('location', ''))}
"""
    for hl in exp.get("highlights", []):
        typst_code += f"- {escape_typst(hl)}\n"

with open("test_compile.typ", "w") as f:
    f.write(typst_code)
    
print("Compiling...")
result = subprocess.run(["typst", "compile", "test_compile.typ", "test_compile.pdf"], capture_output=True, text=True)
print("Stdout:", result.stdout)
print("Stderr:", result.stderr)
print("Return code:", result.returncode)
