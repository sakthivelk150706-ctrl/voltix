import sys

with open('server.py', 'r') as f:
    lines = f.readlines()

new_lines = []
in_do_post = False
indent = "    "

for line in lines:
    if line.startswith("    def do_POST(self):"):
        new_lines.append(line)
        new_lines.append("        try:\n")
        in_do_post = True
        continue
    
    if in_do_post:
        if line.startswith("if __name__ == '__main__':"):
            in_do_post = False
            new_lines.append("        except Exception as e:\n")
            new_lines.append("            import traceback\n")
            new_lines.append("            traceback.print_exc()\n")
            new_lines.append("            return self.send_json({\"error\": \"Internal server error: \" + str(e)}, 500)\n\n")
            new_lines.append(line)
        else:
            if line.startswith("        ") and "content_length =" not in line and "post_data =" not in line and "data = json.loads" not in line and "conn =" not in line:
                new_lines.append("    " + line)
            elif "content_length =" in line:
                new_lines.append("            content_length = int(self.headers.get('Content-Length', 0))\n")
            elif "post_data =" in line:
                new_lines.append("            post_data = self.rfile.read(content_length) if content_length > 0 else b''\n")
            elif "data = json.loads" in line:
                new_lines.append("            data = json.loads(post_data.decode('utf-8')) if post_data else {}\n")
            elif "conn = sqlite3.connect" in line:
                new_lines.append("            conn = sqlite3.connect(DB_FILE)\n")
            else:
                new_lines.append(line)
    else:
        new_lines.append(line)

with open('server.py', 'w') as f:
    f.writelines(new_lines)
