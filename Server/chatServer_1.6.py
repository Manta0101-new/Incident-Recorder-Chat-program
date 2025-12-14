import socket
import threading
import datetime
import os
import traceback
from PIL import Image
import io
import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext, Menu, Toplevel, Checkbutton, IntVar
import sys

# --- Configuration & Globals ---
# Default settings
DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 57001
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"
LOG_FILE = "chat_server.log"
FILES_DIR = "files"  # Subdirectory for storing received files

# Server State Variables
HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
server_socket = None
server_thread = None
is_server_running = False

# Lists
clients = []        # Keeps track of sockets for broadcasting
client_names = []   # Keeps track of names for legacy broadcast logic
authorizedUsers = [] # List of allowed usernames
connectedClients = [] # List of dictionaries: {'name': name, 'ip': ip, 'conn': connection_object}

# --- IO Redirection Class ---
class IORedirector(object):
    """A custom class to redirect stdout to both the terminal and a Tkinter Text widget."""
    def __init__(self, text_area):
        self.text_area = text_area
        self.terminal = sys.stdout # Save the original stdout

    def write(self, str):
        # Write to the original terminal (so you can still see it in your IDE)
        if self.terminal:
            self.terminal.write(str)
        
        # Write to the GUI safely using .after() to avoid threading issues
        # We perform the GUI update on the main thread
        try:
            self.text_area.after(0, self._append_text, str)
        except:
            pass # Handle edge case where window is closed during write

    def _append_text(self, str):
        # Temporarily enable the widget to write data, then disable it again
        self.text_area.configure(state='normal')
        self.text_area.insert(tk.END, str)
        self.text_area.see(tk.END) # Auto-scroll to the bottom
        self.text_area.configure(state='disabled')

    def flush(self):
        # Required for file-like objects
        if self.terminal:
            self.terminal.flush()

# --- Original Server Helper Functions ---

def log_message(source, message_type, content_size=None, content=None, filename=None, status="INFO"):
    """
    Logs the message event with a UTC timestamp and saves files/images.
    """
    utc_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Ensure files directory exists
    if not os.path.exists(FILES_DIR):
        os.makedirs(FILES_DIR)
    
    if message_type == "IMAGE":
        log_entry = f"[{utc_time}] [{status}] [{source}]: Sent IMAGE"
        try:
            if content is None and content_size is None:
                raise ValueError("No image data provided for saving")
            new_filename = f"{utc_time.replace(':', '-')}_image.png"
            destination = os.path.join(FILES_DIR, new_filename)
            if not isinstance(content, bytes):
                try:
                    content = bytes(content)
                except Exception as conv_error:
                    print(f"Conversion Error: {conv_error}")
                    raise ValueError(f"Cannot convert {type(content)} to bytes")
            if len(content) == 0:
                raise ValueError("Empty image data")
            with open(destination, 'wb') as f:
                f.write(content)
            try:
                with Image.open(io.BytesIO(content)) as img:
                    converted_img = img.convert('RGBA')
                    converted_img.save(destination, format='PNG')
            except Exception as img_error:
                print(f"Pillow Image Processing Error: {img_error}")
            if os.path.exists(destination):
                saved_size = os.path.getsize(destination)
                log_entry = f"[{utc_time}] [{status}] [{source}]: Sent IMAGE ({saved_size} bytes) - Saved as {os.path.join(FILES_DIR, new_filename)}"
                print(f"Image saved successfully: {destination}")
            else:
                log_entry = f"[{utc_time}] [ERROR] [{source}]: Image file creation failed"
                print("Image file was not created")
        except Exception as e:
            log_entry = f"[{utc_time}] [ERROR] [{source}]: Image Logging Failed - {str(e)}"
            print(f"Full error details: {traceback.format_exc()}")
    
    elif message_type == "FILE":
        log_entry = f"[{utc_time}] [{status}] [{source}]: Sent FILE"
        try:
            if content is None and content_size is None:
                raise ValueError("No file data provided for saving")
            if filename is None:
                filename = f"{utc_time.replace(':', '-')}_file"
            else:
                filename = f"{utc_time.replace(':', '-')}_{filename}"
            destination = os.path.join(FILES_DIR, filename)
            if not isinstance(content, bytes):
                try:
                    content = bytes(content)
                except Exception as conv_error:
                    print(f"Conversion Error: {conv_error}")
                    raise ValueError(f"Cannot convert {type(content)} to bytes")
            if len(content) == 0:
                raise ValueError("Empty file data")
            with open(destination, 'wb') as f:
                f.write(content)
            if os.path.exists(destination):
                saved_size = os.path.getsize(destination)
                log_entry = f"[{utc_time}] [{status}] [{source}]: Sent FILE ({saved_size} bytes) - Saved as {os.path.join(FILES_DIR, filename)}"
                print(f"File saved successfully: {destination}")
            else:
                log_entry = f"[{utc_time}] [ERROR] [{source}]: File creation failed"
                print("File was not created")
        except Exception as e:
            log_entry = f"[{utc_time}] [ERROR] [{source}]: File Logging Failed - {str(e)}"
            print(f"Full error details: {traceback.format_exc()}")
    
    elif message_type == "TEXT":
        log_entry = f"[{utc_time}] [{status}] [{source}]: {content_size or 'No content'}"
    else:
        log_entry = f"[{utc_time}] [{status}] [{source}]: {message_type}"

    # PRINT to console (which is now redirected to GUI)
    print(log_entry)
    
    # Write to file
    with open(LOG_FILE, 'a', encoding=FORMAT) as f:
        f.write(log_entry + '\n')
    
    return utc_time.encode(FORMAT)

def broadcast(message):
    """Sends a message to all connected clients."""
    for client in clients[:]:
        try:
            client.sendall(message)
        except:
            pass

def stop_server_logic():
    """Logic to stop the server, close sockets, and reset state."""
    global is_server_running, server_socket, clients, client_names, connectedClients
    
    is_server_running = False
    
    for client in clients:
        try:
            client.close()
        except:
            pass
    
    clients.clear()
    client_names.clear()
    connectedClients.clear()
    
    if server_socket:
        try:
            server_socket.close()
        except:
            pass
    
    print("[SERVER] Stopped.")

def start_server_thread():
    """Starts the server in a new thread."""
    global server_thread, is_server_running
    if not is_server_running:
        is_server_running = True
        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()

def run_server():
    """Main server loop."""
    global server_socket, HOST, PORT, is_server_running
    
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        
        print(f"[LISTENING] Server is listening on {HOST}:{PORT}")
        log_message("SERVER", "STARTUP", f"Server started on {HOST}:{PORT}")
        
        while is_server_running:
            try:
                conn, addr = server_socket.accept()
                thread = threading.Thread(target=handle_client, args=(conn, addr))
                thread.start()
                print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 2}") 
            except OSError:
                break
            except Exception as e:
                print(f"[ERROR] Accept error: {e}")
                break
                
    except Exception as e:
        print(f"[ERROR] Server failed to start: {e}")
        is_server_running = False

def handle_client(conn, addr):
    """Handles communication with a single client."""
    client_ip = addr[0]
    name = None
    
    try:
        name_data = conn.recv(1024)
        if not name_data:
            conn.close()
            return
            
        name = name_data.decode(FORMAT)
        
        if name not in authorizedUsers:
            print(f"[AUTH FAILED] {name} is not in authorized list.")
            conn.sendall("unauthorized connection".encode(FORMAT))
            conn.close()
            return

        user_entry = next((item for item in connectedClients if item["name"] == name), None)
        
        if user_entry:
            if user_entry['ip'] != client_ip:
                print(f"[AUTH FAILED] {name} attempted connection from different IP {client_ip}.")
                conn.sendall("unauthorized connection".encode(FORMAT))
                conn.close()
                return
        else:
            connectedClients.append({'name': name, 'ip': client_ip, 'conn': conn})

        client_names.append(name)
        clients.append(conn)
        
        log_message("SERVER", "CONNECTION", f"{addr} connected as {name}")
        broadcast(f"[SERVER] {name} joined the chat!".encode(FORMAT))

        connected = True
        while connected and is_server_running:
            try:
                data = conn.recv(1024) 
                if not data:
                    break 
                
                is_file = False
                is_image = False
                message_to_broadcast = data
                message_type = "TEXT"
                log_content = ""
                
                utc_timestamp = log_message(name, "RECEIVE", len(data), status="LOGGING")

                if data.startswith(b"IMAGE|") or data.startswith(b"FILE|"):
                    if data.startswith(b"IMAGE|"):
                        message_type = "IMAGE"
                        is_image = True
                        header_marker = b"IMAGE|"
                    else: 
                        message_type = "FILE"
                        is_file = True
                        header_marker = b"FILE|"
                    
                    header_start = data.find(header_marker)
                    first_split = data.find(b"|", header_start + len(header_marker))
                    second_split = data.find(b"|", first_split + 1)
                    
                    if second_split != -1:
                        header_end_index = second_split + 1
                        if is_file:
                            filename = data[header_start + len(header_marker):first_split].decode(FORMAT)
                            size_bytes = data[first_split + 1:second_split]
                            content_size = int(size_bytes.decode(FORMAT))
                            log_content = f"{filename}, {content_size} bytes"
                        else: 
                            content_size = int(data[header_start + len(header_marker):first_split].decode(FORMAT))
                            log_content = f"{content_size} bytes"
                            header_end_index = first_split + 1
                        
                        content_data = data[header_end_index:]
                        remaining_size = content_size - len(content_data)
                        while remaining_size > 0:
                            chunk = conn.recv(min(remaining_size, 4096))
                            if not chunk:
                                raise Exception("Client closed during transfer.")
                            content_data += chunk
                            remaining_size -= len(chunk)
                        
                        message_to_broadcast = data[:header_end_index] + content_data

                        # FIX: Pass content_data to log_message and capture timestamp
                        if is_image:
                            utc_timestamp = log_message(name, "IMAGE", content_size=content_size, content=content_data)
                        elif is_file:
                            utc_timestamp = log_message(name, "FILE", content_size=content_size, content=content_data, filename=filename)
                    else:
                        log_message(name, message_type, "N/A", status="ERROR: Malformed Header")
                        continue
                
                elif data.decode(FORMAT).startswith(DISCONNECT_MESSAGE):
                    connected = False
                    continue
                
                if message_type == "TEXT":
                    original_text = data.decode(FORMAT)
                    log_content = original_text
                    timestamped_message = f"[{utc_timestamp.decode(FORMAT)} {name}]: {original_text}"
                    message_to_broadcast = timestamped_message.encode(FORMAT)
                
                broadcast(message_to_broadcast)
                    
            except Exception as e:
                log_message(name, "ERROR", str(e), status="CRITICAL ERROR")
                connected = False

    except Exception as e:
        print(f"Error handling client {addr}: {e}")
    
    finally:
        if conn in clients:
            clients.remove(conn)
        if name in client_names:
            client_names.remove(name)
        
        for client_data in connectedClients:
            if client_data['name'] == name and client_data['conn'] == conn:
                connectedClients.remove(client_data)
                break

        try:
            conn.close()
        except:
            pass
            
        if name:
            log_message("SERVER", "DISCONNECTION", name)
            broadcast(f"[SERVER] {name} has left the chat.".encode(FORMAT))


# --- GUI Class ---

class ServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat Server Manager")
        self.root.geometry("500x500") # Increased height for log box
        
        # 1. Status Label
        self.status_label = tk.Label(root, text="Server Status: OFF", fg="red", font=("Arial", 14))
        self.status_label.pack(pady=10)
        
        # 2. Toggle Button
        self.toggle_btn = tk.Button(root, text="Turn Server ON", command=self.toggle_server, height=2, width=20)
        self.toggle_btn.pack(pady=5)
        
        # 3. Info Label
        self.info_label = tk.Label(root, text=f"Config: {HOST}:{PORT}")
        self.info_label.pack(pady=5)
        
        # 4. Output Log Box (Readonly)
        tk.Label(root, text="Server Output:").pack(anchor="w", padx=10)
        
        self.log_area = scrolledtext.ScrolledText(root, state='disabled', height=15)
        self.log_area.pack(padx=10, pady=(0, 10), fill=tk.BOTH, expand=True)
        
        # --- REDIRECT STDOUT TO THE TEXT BOX ---
        # This will make any 'print' statement show up in the text box
        sys.stdout = IORedirector(self.log_area)
        
        self.create_menus()

    def create_menus(self):
        menubar = Menu(self.root)
        self.root.config(menu=menubar)
        
        config_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configuration", menu=config_menu)
        config_menu.add_command(label="Port and IP", command=self.open_port_ip_config)
        
        users_menu = Menu(menubar, tearoff=0)
        menubar.add_command(label="Users", command=self.open_users_config)
        
        conn_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Connections", menu=conn_menu)
        conn_menu.add_command(label="Connected Clients", command=self.open_connected_clients)
        
        # About menu
        menubar.add_command(label="About", command=self.open_about)
        
        # Exit menu
        menubar.add_command(label="Exit", command=self.exit_application)

    def toggle_server(self):
        global is_server_running
        if not is_server_running:
            start_server_thread()
            self.status_label.config(text="Server Status: ON", fg="green")
            self.toggle_btn.config(text="Turn Server OFF")
        else:
            stop_server_logic()
            self.status_label.config(text="Server Status: OFF", fg="red")
            self.toggle_btn.config(text="Turn Server ON")
        
        self.update_info_label()

    def update_info_label(self):
        self.info_label.config(text=f"Config: {HOST}:{PORT}")

    def open_port_ip_config(self):
        config_win = Toplevel(self.root)
        config_win.title("Configuration: Port and IP")
        config_win.geometry("300x200")
        
        tk.Label(config_win, text="IP Address:").pack(pady=5)
        ip_entry = tk.Entry(config_win)
        ip_entry.insert(0, HOST)
        ip_entry.pack(pady=5)
        
        tk.Label(config_win, text="Port:").pack(pady=5)
        port_entry = tk.Entry(config_win)
        port_entry.insert(0, str(PORT))
        port_entry.pack(pady=5)
        
        def save_config():
            global HOST, PORT, is_server_running
            new_ip = ip_entry.get()
            try:
                new_port = int(port_entry.get())
                if new_ip != HOST or new_port != PORT:
                    if is_server_running:
                        msg = "[SERVER] Server shutting down, new IP and port assigned.".encode(FORMAT)
                        broadcast(msg)
                        log_message("SERVER", "CONFIG CHANGE", "Restarting with new IP/Port")
                        stop_server_logic()
                        HOST = new_ip
                        PORT = new_port
                        start_server_thread()
                        self.status_label.config(text="Server Status: ON", fg="green")
                        self.toggle_btn.config(text="Turn Server OFF")
                    else:
                        HOST = new_ip
                        PORT = new_port
                        
                    self.update_info_label()
                    messagebox.showinfo("Success", f"Server configured to {HOST}:{PORT}")
                    config_win.destroy()
                else:
                    config_win.destroy()
            except ValueError:
                messagebox.showerror("Error", "Port must be an integer.")

        btn_frame = tk.Frame(config_win)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Save", command=save_config).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=config_win.destroy).pack(side=tk.LEFT, padx=10)

    def open_users_config(self):
        user_win = Toplevel(self.root)
        user_win.title("Authorized Users")
        user_win.geometry("300x400")
        
        tk.Label(user_win, text="Add users (one per line):").pack(pady=5)
        
        txt_area = scrolledtext.ScrolledText(user_win, width=30, height=15)
        txt_area.pack(pady=5)
        
        current_text = "\n".join(authorizedUsers)
        txt_area.insert(tk.END, current_text)
        
        def save_users():
            global authorizedUsers
            content = txt_area.get("1.0", tk.END).strip()
            if content:
                authorizedUsers[:] = [line.strip() for line in content.split('\n') if line.strip()]
            else:
                authorizedUsers.clear()
            
            messagebox.showinfo("Saved", "Authorized users list updated.")
            user_win.destroy()

        btn_frame = tk.Frame(user_win)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Save", command=save_users).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=user_win.destroy).pack(side=tk.LEFT, padx=10)

    def open_connected_clients(self):
        client_win = Toplevel(self.root)
        client_win.title("Connected Clients")
        client_win.geometry("300x400")
        
        tk.Label(client_win, text="Uncheck to disconnect client:").pack(pady=10)
        check_vars = {}
        frame = tk.Frame(client_win)
        frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        if not connectedClients:
            tk.Label(frame, text="No clients connected.").pack()
        
        for i, client_data in enumerate(connectedClients):
            var = IntVar(value=1)
            check_vars[i] = var
            label_text = f"{client_data['name']} ({client_data['ip']})"
            cb = Checkbutton(frame, text=label_text, variable=var)
            cb.pack(anchor="w")
            
        def save_connections():
            indices_to_remove = [i for i, var in check_vars.items() if var.get() == 0]
            if not indices_to_remove:
                client_win.destroy()
                return

            clients_to_kick = []
            for i in indices_to_remove:
                clients_to_kick.append(connectedClients[i])
            
            for client_data in clients_to_kick:
                try:
                    client_data['conn'].close()
                    print(f"Forcefully closed connection for {client_data['name']}")
                except Exception as e:
                    print(f"Error closing socket: {e}")
                
                response = messagebox.askyesno(
                    "Remove Entry", 
                    f"Should {client_data['name']} be removed from the connectedClients list?"
                )
                if response:
                    if client_data in connectedClients:
                        connectedClients.remove(client_data)
                        
            client_win.destroy()

        btn_frame = tk.Frame(client_win)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Save", command=save_connections).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=client_win.destroy).pack(side=tk.LEFT, padx=10)

    def open_about(self):
        """Opens the About window with author and license information."""
        about_win = Toplevel(self.root)
        about_win.title("About")
        about_win.geometry("600x500")
        
        # Create a frame for content
        content_frame = tk.Frame(about_win)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Scrolled text widget
        text_area = scrolledtext.ScrolledText(content_frame, wrap=tk.WORD, width=70, height=25)
        text_area.pack(fill=tk.BOTH, expand=True)
        
        # About text
        about_text = """Author: Kenneth Ray

This program is released under the MIT License

---

MIT License

Copyright (c) 2025 Kenneth Ray

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        
        text_area.insert(tk.END, about_text)
        text_area.configure(state='disabled')  # Make it read-only
        
        # OK button
        ok_btn = tk.Button(about_win, text="OK", command=about_win.destroy, width=10)
        ok_btn.pack(pady=10)

    def exit_application(self):
        """Closes all connections and exits the application."""
        if is_server_running:
            stop_server_logic()
        self.root.destroy()
        os._exit(0)

if __name__ == "__main__":
    print("[STARTING] GUI...")
    root = tk.Tk()
    app = ServerGUI(root)
    
    def on_closing():
        if is_server_running:
            stop_server_logic()
        root.destroy()
        os._exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()