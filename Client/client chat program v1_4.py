import socket
import threading
import tkinter as tk
from tkinter import simpledialog, Toplevel, filedialog, messagebox
import io
from PIL import Image, ImageGrab, ImageTk, ImageDraw 
import os
import tempfile
import subprocess
import platform
from datetime import datetime 

# Client settings
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"

class ChatClient:
    # Default settings
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_PORT = 57001
    
    def __init__(self, master):
        self.master = master
        master.title("Python Incident Recorder Chat Client")
        
        self.client = None
        self.current_host = self.DEFAULT_HOST
        self.current_port = self.DEFAULT_PORT
        self.name = None
        self.running = False 

        # --- Connection Logic ---
        try:
            # 1. Attempt connection immediately
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((self.DEFAULT_HOST, self.DEFAULT_PORT))
            
            # 2. Prompt for Name
            self.name = simpledialog.askstring("Name", "Please enter your chat name:", parent=self.master)
            if not self.name:
                self.on_closing()
                return

            # 3. Send Name and Start Setup
            self.client.send(self.name.encode(FORMAT))
            self.setup_gui()
            self.start_threads()

        except ConnectionRefusedError:
            messagebox.showerror(
                "Connection Error", 
                f"Could not connect to server at {self.DEFAULT_HOST}:{self.DEFAULT_PORT}. Ensure the server is running."
            )
            self.on_closing()
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred during initialization: {e}")
            self.on_closing()
        # ------------------------


    def setup_gui(self):
        """Initializes all Tkinter widgets after a successful connection."""
        
        # Ensure the window is clear before setting up the chat interface
        for widget in self.master.winfo_children():
            widget.destroy()

        # 1. --- Menu Bar Setup (NEW) ---
        menubar = tk.Menu(self.master)
        self.master.config(menu=menubar)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        # Configuration Sub-menu
        config_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Configuration", menu=config_menu)
        config_menu.add_command(label="Setup", command=self.on_setup_click) 

        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        
        # Help Menu (NEW)
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.on_about_click)

        # 2. --- GUI Elements using grid (Existing logic) ---
        
        self.master.grid_rowconfigure(0, weight=1)
        self.master.grid_columnconfigure(0, weight=1)
        
        # Data storage and references
        self.image_references = [] # Holds Tkinter PhotoImage objects to prevent garbage collection
        self.original_images = {} # Stores original PIL Image objects for full-screen viewer
        self.received_files = {} # Stores received file data and names by a unique tag ID
        self.pending_file_data = None 
        self.pending_file_name = None 
        self.pending_image_bytes = None
        self.file_icon = self._create_file_icon()

        self.chat_log = tk.Text(self.master, state='disabled', wrap='word', height=20, width=50, font=('Arial', 10))
        self.chat_log.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="nsew") 
        self.chat_log.tag_bind("img_tag", "<Button-1>", self.on_image_click)
        self.chat_log.tag_bind("file_tag", "<Button-1>", self.on_file_icon_click) 

        # Input Frame (Row 1)
        input_frame = tk.Frame(self.master)
        input_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1) 
        
        # Action Button Frame (Row 2, spanning the width)
        button_frame = tk.Frame(self.master)
        button_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        
        # --- INPUT TEXT WIDGET (5 rows) ---
        self.input_field = tk.Text(input_frame, height=5, width=50, wrap='word', font=('Arial', 10))
        self.input_field.grid(row=0, column=0, sticky="ew") 
        
        # --- SEND FILE BUTTON ---
        self.file_button = tk.Button(button_frame, text="Select & Send File", command=self.open_file_dialog)
        self.file_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        # --- KEY BINDINGS ---
        self.input_field.bind("<Key-Return>", self.send_smart_message_event) 
        self.input_field.bind("<Control-v>", self.handle_paste_image)
        self.input_field.bind("<Command-v>", self.handle_paste_image)
        
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.insert_message(f"[INFO] Connected to {self.current_host}:{self.current_port}.")
        self.insert_message("[INFO] Use the 'Select & Send File' button for file transfer, or paste an image (Ctrl+V) and hit Enter to send.")
        self.insert_message("[INFO] Click a received file icon to open it in your default application.")

    def start_threads(self):
        # 3. Start Receiving Thread
        self.running = True
        receive_thread = threading.Thread(target=self.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()

    def _create_file_icon(self):
        """Creates a simple file icon (64x64) for display in the chat log."""
        try:
            size = (64, 64) 
            img = Image.new('RGBA', size, (255, 255, 255, 0))
            
            draw = ImageDraw.Draw(img)
            draw.rectangle([8, 8, 56, 56], fill=(50, 50, 200), outline=(0, 0, 0))
            draw.line([52, 8, 52, 56], fill=(255, 255, 255), width=5)
            
            tk_icon = ImageTk.PhotoImage(img)
            self.image_references.append(tk_icon) 
            return tk_icon
        except Exception as e:
            print(f"Could not create file icon: {e}. Using None.")
            return None
            
    # --- MENU HANDLERS (NEW) ---
    
    def on_setup_click(self):
        """Opens a dialog to configure server IP and Port."""
        setup_window = Toplevel(self.master)
        setup_window.title("Network Setup")
        
        tk.Label(setup_window, text="IP Address:").grid(row=0, column=0, padx=10, pady=10, sticky='w')
        ip_var = tk.StringVar(value=self.current_host)
        ip_entry = tk.Entry(setup_window, textvariable=ip_var, width=20)
        ip_entry.grid(row=0, column=1, padx=10, pady=10)
        
        tk.Label(setup_window, text="Port:").grid(row=1, column=0, padx=10, pady=10, sticky='w')
        port_var = tk.StringVar(value=str(self.current_port))
        port_entry = tk.Entry(setup_window, textvariable=port_var, width=20)
        port_entry.grid(row=1, column=1, padx=10, pady=10)
        
        def save_and_reconnect():
            new_ip = ip_var.get()
            new_port = port_var.get()
            
            try:
                new_port_int = int(new_port)
                # Only update and reconnect if values changed
                if new_ip != self.current_host or new_port_int != self.current_port:
                    self.current_host = new_ip
                    self.current_port = new_port_int
                    self.insert_message(f"[INFO] Configuration saved. Attempting reconnect to {new_ip}:{new_port_int}...")
                    self.reconnect_to_server()
                setup_window.destroy()
            except ValueError:
                messagebox.showerror("Input Error", "Port must be a valid integer.")
                
        tk.Button(setup_window, text="Save & Reconnect", command=save_and_reconnect).grid(row=2, column=0, columnspan=2, pady=10)
        setup_window.transient(self.master)
        setup_window.grab_set()
        self.master.wait_window(setup_window)

    def on_about_click(self):
        """Opens a Toplevel window with the author, version, and license information."""
        
        mit_license_text = """
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
        about_content = (
            "Author: Kenneth Ray\n"
            "Version 1.0\n"
            "This is released under the MIT license.\n\n"
            "--- MIT License ---\n"
            f"{mit_license_text.strip()}"
        )
        
        about_window = Toplevel(self.master)
        about_window.title("About Python Chat Client")
        about_window.geometry("500x450")
        about_window.resizable(False, False)
        
        rtb = tk.Text(about_window, wrap='word', width=60, height=20, font=('Courier', 9))
        rtb.insert(tk.END, about_content)
        rtb.config(state='disabled')
        rtb.pack(padx=10, pady=10, fill='both', expand=True)

        about_window.transient(self.master)
        about_window.grab_set()
        self.master.wait_window(about_window)

    def reconnect_to_server(self):
        """Closes current connection and attempts to reconnect with new settings."""
        self.running = False
        try:
            if self.client:
                self.client.close()
        except:
            pass
        
        # Give thread a moment to stop
        import time
        time.sleep(0.1)

        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((self.current_host, self.current_port))
            
            # Re-send Name
            self.client.send(self.name.encode(FORMAT))
            
            self.insert_message(f"[INFO] Successfully reconnected to {self.current_host}:{self.current_port}.")
            
            # Restart receiver thread
            self.start_threads()
            
        except Exception as e:
            messagebox.showerror(
                "Reconnection Failed", 
                f"Could not reconnect to server at {self.current_host}:{self.current_port}. Error: {e}"
            )
            self.insert_message("[ERROR] Reconnection failed. Client is currently disconnected.")


    # --- FILE ICON CLICK HANDLER ---
    def on_file_icon_click(self, event):
        """When a file icon is clicked, open the file in the default application."""
        try:
            click_index = self.chat_log.index("@%s,%s" % (event.x, event.y))
            image_tags = self.chat_log.tag_names(click_index)
            
            file_id_tag = next((tag for tag in image_tags if tag.startswith("file_id_")), None)

            if file_id_tag and file_id_tag in self.received_files:
                filename, file_data = self.received_files[file_id_tag]
                
                self.master.after(0, lambda: self.open_received_file_in_app(filename, file_data))
                
            else:
                self.insert_message("[ERROR] Could not find file data associated with this icon.")

        except Exception as e:
            print(f"Error handling file icon click: {e}")

    # --- FILE OPENING LOGIC ---
    def open_received_file_in_app(self, filename, file_data):
        """Saves the file to a temp location and opens it using the OS default application."""
        try:
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, filename)

            with open(temp_path, 'wb') as f:
                f.write(file_data)
            
            os_name = platform.system()
            
            if os_name == "Windows":
                os.startfile(temp_path)
            elif os_name == "Darwin":
                subprocess.run(['open', temp_path])
            else:
                subprocess.run(['xdg-open', temp_path])
                
            self.insert_message(f"[FILE OPENED] Opened '{filename}' in default application (Temp path: {temp_path}).")
            
        except Exception as e:
            self.insert_message(f"[ERROR] Failed to open file {filename}: {e}")
            self.insert_message(f"[HINT] If the file failed to open, it may have been saved to the temp folder.")

    # --- FILE DIALOG HANDLER ---
    def open_file_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Select a file to send"
        )
        if file_path:
            self.prepare_file_for_sending(file_path)

    def prepare_file_for_sending(self, path):
        try:
            with open(path, 'rb') as f:
                file_bytes = f.read()
            
            self.pending_image_bytes = None
            
            self.pending_file_data = file_bytes
            self.pending_file_name = os.path.basename(path)
            
            self.clear_input_field()
            self.insert_input_text(f"[File Ready: {self.pending_file_name}, {len(file_bytes)} bytes - Press Enter to Send]")

        except Exception as e:
            self.pending_file_data = None
            self.pending_file_name = None
            self.insert_message(f"[ERROR] Could not read file {path}: {e}")

    # --- HELPER METHODS FOR TEXT WIDGET INPUT ---
    def get_input_text(self):
        return self.input_field.get("1.0", tk.END).strip()

    def clear_input_field(self):
        self.input_field.delete("1.0", tk.END)

    def insert_input_text(self, text):
        self.input_field.insert(tk.END, text)
    # ---------------------------------------------

    # --- SENDING LOGIC ---
    def send_smart_message_event(self, event):
        self.send_smart_message()
        return "break"

    def send_smart_message(self):
        
        if self.pending_image_bytes:
            # SEND IMAGE
            image_bytes = self.pending_image_bytes
            try:
                header = f"IMAGE|{len(image_bytes)}|".encode(FORMAT)
                self.client.sendall(header + image_bytes)
                self.insert_message(f"[YOU] Sent image ({len(image_bytes)} bytes).")
            except Exception as e:
                self.insert_message(f"[ERROR] Failed to send image: {e}")

            self.pending_image_bytes = None
            self.clear_input_field()

        elif self.pending_file_data and self.pending_file_name:
            # SEND FILE
            file_bytes = self.pending_file_data
            file_name = self.pending_file_name
            try:
                header = f"FILE|{file_name}|{len(file_bytes)}|".encode(FORMAT)
                self.client.sendall(header + file_bytes)
                self.insert_message(f"[YOU] Sent file: {file_name} ({len(file_bytes)} bytes).")
            except Exception as e:
                self.insert_message(f"[ERROR] Failed to send file: {e}")
            
            self.pending_file_data = None
            self.pending_file_name = None
            self.clear_input_field()

        else:
            # SEND TEXT
            message = self.get_input_text()
            if message:
                try:
                    self.client.send(message.encode(FORMAT))
                    self.clear_input_field()
                except:
                    self.insert_message("[ERROR] Could not send message.")

    # --- RECEIVING/DISPLAYING LOGIC ---

    def display_received_file(self, filename, file_data):
        """Displays a clickable icon and filename in the chat log, prefixed by UTC timestamp."""
        try:
            utc_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            
            file_tag_id = "file_id_" + str(len(self.received_files))
            self.received_files[file_tag_id] = (filename, file_data)
            
            self.chat_log.config(state='normal')
            
            self.chat_log.insert(tk.END, f"\n[{utc_time}] [FILE RECEIVED] Click to Open: ") 
            
            if self.file_icon:
                file_mark = self.chat_log.image_create(tk.END, image=self.file_icon)
                self.chat_log.tag_add("file_tag", file_mark) # Clickable tag
                self.chat_log.tag_add(file_tag_id, file_mark) # Unique data tag

            self.chat_log.insert(tk.END, f" {filename} ({len(file_data)} bytes)\n")
            
            self.chat_log.yview(tk.END)
            self.chat_log.config(state='disabled')
            
        except Exception as e:
            self.insert_message(f"[ERROR] Failed to display received file placeholder: {e}")


    def display_received_text(self, message):
        self.chat_log.config(state='normal')
        self.chat_log.insert(tk.END, message + '\n')
        self.chat_log.yview(tk.END)
        self.chat_log.config(state='disabled')

    def receive_messages(self):
        while self.running:
            try:
                # Optimized initial receive size
                data = self.client.recv(1024) 
                if not data:
                    break 
                
                is_binary = data.startswith(b"IMAGE|") or data.startswith(b"FILE|")
                
                if is_binary:
                    is_image = data.startswith(b"IMAGE|")
                    header_marker = b"IMAGE|" if is_image else b"FILE|"
                    
                    header_start = data.find(header_marker)
                    first_split = data.find(b"|", header_start + len(header_marker))
                    
                    if is_image:
                        second_split = first_split
                        content_size = int(data[header_start + len(header_marker):first_split].decode(FORMAT))
                    else:
                        second_split = data.find(b"|", first_split + 1)
                        filename = data[header_start + len(header_marker):first_split].decode(FORMAT)
                        content_size = int(data[first_split + 1:second_split].decode(FORMAT))
                        
                    if second_split != -1:
                        header_end_index = second_split + 1
                        content_data = data[header_end_index:]
                        
                        remaining_size = content_size - len(content_data)
                        while remaining_size > 0:
                            chunk = self.client.recv(min(remaining_size, 4096))
                            if not chunk:
                                raise Exception("Connection closed during data transfer.")
                            content_data += chunk
                            remaining_size -= len(chunk)

                        if is_image:
                            self.display_image(content_data)
                        else:
                            self.display_received_file(filename, content_data)
                        
                        continue
                        
                message = data.decode(FORMAT)
                if message == DISCONNECT_MESSAGE:
                    break
                
                self.display_received_text(message)
                
            except Exception as e:
                print(f"Error in receiver: {e}")
                self.running = False
                break
        
        self.insert_message("[DISCONNECTED] Lost connection to the server.")
        # Ensure the client is closed after the loop breaks
        if self.client:
            self.client.close()

    # --- Utility and Image Methods ---
    
    def handle_paste_image(self, event):
        """Prepares clipboard image for sending via Ctrl+V or Cmd+V."""
        self.pending_file_data = None
        self.pending_file_name = None
        # Use after(50) to allow the OS to fully place the content in the clipboard
        self.master.after(50, lambda: self._process_clipboard_after_paste())
        return "break" # Prevent the default paste action

    def _process_clipboard_after_paste(self):
        try:
            img = ImageGrab.grabclipboard()
            
            if img is None or not isinstance(img, Image.Image):
                self.pending_image_bytes = None
                return

            byte_arr = io.BytesIO()
            original_img = img.copy() 
            # Resize thumbnail for input field display (not sending)
            max_size = (300, 300) 
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save the *original* image to bytes for sending as JPEG
            original_img.save(byte_arr, format='JPEG')
            image_bytes = byte_arr.getvalue()
            
            self.pending_image_bytes = image_bytes
            
            self.clear_input_field()
            self.insert_input_text(f"[Image Ready: {original_img.width}x{original_img.height} - Press Enter to Send]")
            
        except Exception as e:
            self.pending_image_bytes = None
            self.insert_message(f"[ERROR] Failed to handle paste: {e}")

    def _resize_image_viewer(self, event, original_img, label):
        """Scales the image to fit the new size of the Toplevel window."""
        
        new_width = max(1, event.width)
        new_height = max(1, event.height)
        
        original_aspect = original_img.width / original_img.height
        
        # Determine the maximum fit size while maintaining aspect ratio
        if new_width / new_height > original_aspect:
            scale_height = new_height
            scale_width = int(scale_height * original_aspect)
        else:
            scale_width = new_width
            scale_height = int(scale_width / original_aspect)

        scale_width = max(1, scale_width)
        scale_height = max(1, scale_height)
        
        # Resize and convert to PhotoImage
        resized_img = original_img.copy().resize((scale_width, scale_height), Image.Resampling.LANCZOS)
        tk_resized_img = ImageTk.PhotoImage(resized_img)
        
        # Update the label and store the reference
        label.config(image=tk_resized_img)
        label.image = tk_resized_img # Crucial to prevent garbage collection

    def on_image_click(self, event):
        """Opens a Toplevel window to view the full-size image."""
        try:
            click_index = self.chat_log.index("@%s,%s" % (event.x, event.y))
            image_tags = self.chat_log.tag_names(click_index)
            image_id_tag = next((tag for tag in image_tags if tag.startswith("img_") and tag != "img_tag"), None)

            if image_id_tag and image_id_tag in self.original_images:
                original_img = self.original_images[image_id_tag]
                
                # 1. Create the Toplevel window
                img_window = Toplevel(self.master)
                img_window.title(f"Full Image View ({original_img.width}x{original_img.height})")

                screen_width = img_window.winfo_screenwidth()
                screen_height = img_window.winfo_screenheight()
                
                initial_width = min(original_img.width, screen_width - 100)
                initial_height = min(original_img.height, screen_height - 100)
                
                img_window.geometry(f"{initial_width}x{initial_height}")

                # 2. Create the initial PhotoImage and Label
                initial_resized_img = original_img.copy().resize((initial_width, initial_height), Image.Resampling.LANCZOS)
                tk_full_img = ImageTk.PhotoImage(initial_resized_img)

                label = tk.Label(img_window, image=tk_full_img, bg='gray')
                label.image = tk_full_img
                label.pack(expand=True, fill='both') 

                # 3. Bind the <Configure> event to the window for resizing
                img_window.bind('<Configure>', 
                                lambda e: self._resize_image_viewer(e, original_img, label))
                                
            else:
                self.insert_message("[ERROR] Could not find original image data or unique tag.")

        except Exception as e:
            print(f"Error handling image click: {e}")

    def display_image(self, image_data):
        """Displays a thumbnail of the received image in the chat log."""
        try:
            utc_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            
            image_stream = io.BytesIO(image_data)
            original_img = Image.open(image_stream)
            
            display_img = original_img.copy()
            max_display_size = (200, 200)
            display_img.thumbnail(max_display_size, Image.Resampling.LANCZOS)
            tk_thumb_img = ImageTk.PhotoImage(display_img)
            
            image_tag_id = "img_" + str(len(self.image_references)) 
            self.original_images[image_tag_id] = original_img
            
            self.chat_log.config(state='normal')
            
            self.chat_log.insert(tk.END, f"\n[{utc_time}] [IMAGE RECEIVED] Click to View: ") 
            
            image_mark = self.chat_log.image_create(tk.END, image=tk_thumb_img)
            
            self.chat_log.tag_add("img_tag", image_mark)
            self.chat_log.tag_add(image_tag_id, image_mark) 
            
            self.chat_log.insert(tk.END, "\n")
            self.image_references.append(tk_thumb_img) 
            self.chat_log.yview(tk.END)
            self.chat_log.config(state='disabled')
            
        except Exception as e:
            print(f"Error in display_image: {e}")
            self.insert_message(f"[ERROR] Failed to display received image: {e}")
    
    def insert_message(self, message):
        """Utility function to safely insert a text message into the chat log."""
        self.chat_log.config(state='normal')
        self.chat_log.insert(tk.END, message + '\n')
        self.chat_log.yview(tk.END)
        self.chat_log.config(state='disabled')

    def on_closing(self):
        """Handles graceful client shutdown and GUI destruction."""
        self.running = False
        try:
            if self.client:
                # Signal disconnect to the server
                self.client.send(DISCONNECT_MESSAGE.encode(FORMAT))
                self.client.close()
        except:
            pass 
        if self.master.winfo_exists():
             self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClient(root)
    root.mainloop()