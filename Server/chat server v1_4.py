import socket
import threading
import datetime
import os
import traceback
from PIL import Image
import io

# Server settings
HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 57001      # Port to listen on
FORMAT = 'utf-8'
DISCONNECT_MESSAGE = "!DISCONNECT"
LOG_FILE = "chat_server.log"

# List to keep track of all connected clients and their names
clients = []
client_names = []

def log_message(source, message_type, content_size=None, content=None, filename=None, status="INFO"):
    """
    Logs the message event with a UTC timestamp and saves files/images.
    """
    utc_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if message_type == "IMAGE":
        log_entry = f"[{utc_time}] [{status}] [{source}]: Sent IMAGE"
        
        try:
            # Validate image data
            if content is None and content_size is None:
                raise ValueError("No image data provided for saving")
            
            # Generate unique PNG filename in current directory
            new_filename = f"{utc_time.replace(':', '-')}_image.png"
            destination = os.path.join(os.getcwd(), new_filename)
            
            # Ensure content is bytes
            if not isinstance(content, bytes):
                try:
                    content = bytes(content)
                except Exception as conv_error:
                    print(f"Conversion Error: {conv_error}")
                    raise ValueError(f"Cannot convert {type(content)} to bytes")
            
            # Verify we actually have image data
            if len(content) == 0:
                raise ValueError("Empty image data")
            
            # Write raw bytes to file
            with open(destination, 'wb') as f:
                f.write(content)
            
            # Attempt to open and convert with Pillow
            try:
                with Image.open(io.BytesIO(content)) as img:
                    converted_img = img.convert('RGBA')
                    converted_img.save(destination, format='PNG')
            except Exception as img_error:
                print(f"Pillow Image Processing Error: {img_error}")
                # If Pillow fails, we still have the raw bytes saved
            
            # Verify file was created
            if os.path.exists(destination):
                saved_size = os.path.getsize(destination)
                log_entry = f"[{utc_time}] [{status}] [{source}]: Sent IMAGE ({saved_size} bytes) - Saved as {new_filename}"
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
            # Validate file data
            if content is None and content_size is None:
                raise ValueError("No file data provided for saving")
            
            # Use provided filename or generate a unique one
            if filename is None:
                filename = f"{utc_time.replace(':', '-')}_file"
            else:
                filename = f"{utc_time.replace(':', '-')}_{filename}"
            # Generate destination path
            destination = os.path.join(os.getcwd(), filename)
            
            # Ensure content is bytes
            if not isinstance(content, bytes):
                try:
                    content = bytes(content)
                except Exception as conv_error:
                    print(f"Conversion Error: {conv_error}")
                    raise ValueError(f"Cannot convert {type(content)} to bytes")
            
            # Verify we actually have file data
            if len(content) == 0:
                raise ValueError("Empty file data")
            
            # Write raw bytes to file
            with open(destination, 'wb') as f:
                f.write(content)
            
            # Verify file was created
            if os.path.exists(destination):
                saved_size = os.path.getsize(destination)
                log_entry = f"[{utc_time}] [{status}] [{source}]: Sent FILE ({saved_size} bytes) - Saved as {filename}"
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

    # Logging logic
    print(log_entry)
    with open(LOG_FILE, 'a', encoding=FORMAT) as f:
        f.write(log_entry + '\n')
    
    return utc_time.encode(FORMAT)

def broadcast(message):
    """Sends a message to all connected clients using sendall for reliable binary transfer."""
    for client in clients:
        try:
            client.sendall(message)
        except:
            # Cleanup logic remains the same
            try:
                index = clients.index(client)
                client_name = client_names[index]
                clients.pop(index)
                client_names.pop(index)
                print(f"[DISCONNECTED] Client {client_name} removed during broadcast failure.")
                client.close()
            except ValueError:
                pass 

def handle_client(conn, addr):
    """Handles all communication with a single client, supporting text, images, and files."""
    
    # 1. Get the client's name (initial message after connection)
    name_data = conn.recv(1024)
    if not name_data:
        conn.close()
        return
        
    name = name_data.decode(FORMAT)
    client_names.append(name)
    clients.append(conn)
    
    log_message("SERVER", "CONNECTION", f"{addr} connected as {name}")
    broadcast(f"[SERVER] {name} joined the chat!".encode(FORMAT))

    connected = True
    while connected:
        try:
            data = conn.recv(1024) 
            if not data:
                break 
            
            is_file = False
            is_image = False
            message_to_broadcast = data
            message_type = "TEXT"
            log_content = ""
            
            # Extract UTC timestamp for protocol consistency
            utc_timestamp = log_message(name, "RECEIVE", len(data), status="LOGGING")

            # --- IMAGE AND FILE HANDLING LOGIC ---
            if data.startswith(b"IMAGE|") or data.startswith(b"FILE|"):
                
                # Determine message type and required header parts
                if data.startswith(b"IMAGE|"):
                    message_type = "IMAGE"
                    is_image = True
                    header_marker = b"IMAGE|"
                else: # Must be FILE
                    message_type = "FILE"
                    is_file = True
                    header_marker = b"FILE|"
                
                # A. Find the header parts in the initial received data
                header_start = data.find(header_marker)
                
                # Find the end of the first '|' (size for IMAGE, filename for FILE)
                first_split = data.find(b"|", header_start + len(header_marker))
                
                # Find the end of the second '|' (size for FILE, data start for IMAGE)
                second_split = data.find(b"|", first_split + 1)
                
                if second_split != -1:
                    
                    header_end_index = second_split + 1
                    
                    if is_file:
                        # Protocol: FILE|filename|size|
                        filename = data[header_start + len(header_marker):first_split].decode(FORMAT)
                        size_bytes = data[first_split + 1:second_split]
                        content_size = int(size_bytes.decode(FORMAT))
                        log_content = f"{filename}, {content_size} bytes"
                    else: # IMAGE
                        # Protocol: IMAGE|size|
                        content_size = int(data[header_start + len(header_marker):first_split].decode(FORMAT))
                        log_content = f"{content_size} bytes"
                        # Reset header_end_index for IMAGE since it only has one split
                        header_end_index = first_split + 1
                    
                    # Initial payload is the remainder of the first recv call
                    content_data = data[header_end_index:]
                    
                    # C. Receive Remaining Data
                    remaining_size = content_size - len(content_data)
                    while remaining_size > 0:
                        chunk = conn.recv(min(remaining_size, 4096))
                        if not chunk:
                            raise Exception("Client closed during transfer.")
                        content_data += chunk
                        remaining_size -= len(chunk)
                    
                    # Reconstruct the full message for broadcast (Header + Data)
                    message_to_broadcast = data[:header_end_index] + content_data

                    # KEY CHANGE: Pass full content to log_message for image and file
                    if is_image:
                        log_message(name, "IMAGE", content_size=content_size, content=content_data)
                    elif is_file:
                        log_message(name, "FILE", content_size=content_size, content=content_data, filename=filename)

                else:
                    # Malformed header, ignore the data
                    log_message(name, message_type, "N/A", status="ERROR: Malformed Header")
                    continue
            
            # --- TEXT HANDLING LOGIC ---
            elif data.decode(FORMAT).startswith(DISCONNECT_MESSAGE):
                connected = False
                continue
            
            if message_type == "TEXT":
                original_text = data.decode(FORMAT)
                log_content = original_text
                
                # Prepend UTC timestamp to text messages before broadcasting
                timestamped_message = f"[{utc_timestamp.decode(FORMAT)} {name}]: {original_text}"
                message_to_broadcast = timestamped_message.encode(FORMAT)
            
            # Log the successful message
            log_message(name, message_type, log_content, status="SENT")
            
            # Broadcast the complete message
            broadcast(message_to_broadcast)
                
        except Exception as e:
            # Handle client disconnection or socket error
            log_message(name, "ERROR", str(e), status="CRITICAL ERROR")
            connected = False

    # Disconnect routine
    try:
        index = clients.index(conn)
        clients.remove(conn)
        conn.close()
        name = client_names.pop(index)
        log_message("SERVER", "DISCONNECTION", name)
        broadcast(f"[SERVER] {name} has left the chat.".encode(FORMAT))
    except Exception:
        pass # Client already removed or error during close

def start():
    """Initializes and runs the server."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[LISTENING] Server is listening on {HOST}:{PORT}")
    log_message("SERVER", "STARTUP", f"Server started and logging to {LOG_FILE}")
    
    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()
        print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")

print("[STARTING] server is starting...")
if __name__ == "__main__":
    start()