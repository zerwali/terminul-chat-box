import socket
import threading
import time
import json
from pathlib import Path
from datetime import datetime

HOST = "127.0.0.1"
PORT = 12345
MAX_CONNECTIONS = 50
MESSAGE_BUFFER_SIZE = 1024

clients = {} 
clients_lock = threading.Lock() 

# ================= LOGGING =================
def log_event(event_type, username="", extra=""):
    """Log events to file for audit trail"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_file = Path("chat_log.txt")
    with open(log_file, "a") as f:
        if extra:
            f.write(f"[{timestamp}] {event_type}: {username} - {extra}\n")
        else:
            f.write(f"[{timestamp}] {event_type}: {username}\n")

# ================= SYSTEM MESSAGE =================
def system_msg(username, msg_type):
    """Generate system messages"""
    messages = {
        "JOIN": f"joined the chat",
        "LEAVE": f"left the chat",
        "KICK": f"was kicked from the chat",
    }
    
    if msg_type in messages:
        return f"[SERVER]: {username} {messages[msg_type]}"
    return f"[SERVER]: {msg_type}"


# ================= BROADCAST =================
def broadcast(message, sender_conn=None, exclude_sender=True):
    """Send message to all connected clients"""
    if isinstance(message, bytes):
        if sender_conn and sender_conn in clients:
            username = clients[sender_conn]["username"]
            full_message = f"[{username}]: {message.decode()}"
        else:
            full_message = message.decode()
    else:
        full_message = message
    
    # Encode once, send to all
    encoded_message = (full_message + "\n").encode()
    
    with clients_lock:
        dead_clients = []
        
        for conn in list(clients):
            # Skip sender if exclude_sender is True
            if exclude_sender and conn == sender_conn:
                continue
            
            try:
                conn.sendall(encoded_message)
            except (BrokenPipeError, ConnectionResetError):
                dead_clients.append(conn)
        
        # Clean up dead connections
        for conn in dead_clients:
            try:
                conn.close()
            except:
                pass
            if conn in clients:
                del clients[conn]


# ================= BROADCAST TO SENDER =================
def broadcast_to_sender(conn, message):
    """Send message only to the sender"""
    encoded_message = (message + "\n").encode()
    try:
        conn.sendall(encoded_message)
    except:
        pass


# ================= ADMIN TOOLS =================
class AdminTools:
    
    @staticmethod
    def list_users():
        """List all connected users"""
        with clients_lock:
            if not clients:
                print("\n[ADMIN] No users connected")
                return
            
            print("\n[ADMIN] Users connected:")
            for i, (conn, client_info) in enumerate(clients.items(), 1):
                username = client_info["username"]
                addr = client_info["addr"]
                print(f"  {i}. {username:15} | {addr[0]}:{addr[1]}")
        print("> ", end="", flush=True)
    
    @staticmethod
    def kick(target_username):
        """Kick a user from the chat"""
        with clients_lock:
            for conn in list(clients):
                if clients[conn]["username"] == target_username:
                    addr = clients[conn]["addr"]
                    
                    # Log the kick
                    log_event("KICK", target_username, str(addr))
                    
                    # Notify others
                    broadcast(system_msg(target_username, "KICK"))
                    
                    # Close connection
                    try:
                        conn.close()
                    except:
                        pass
                    
                    del clients[conn]
                    print(f"[ADMIN] {target_username} kicked successfully")
                    return
        
        print(f"[ADMIN] User '{target_username}' not found")
    
    @staticmethod
    def send_announcement(message):
        """Send server announcement to all"""
        announcement = f"[ANNOUNCEMENT]: {message}"
        broadcast(announcement)
        print(f"[ADMIN] Announcement sent")
    
    @staticmethod
    def server_info():
        """Show server info"""
        with clients_lock:
            user_count = len(clients)
        
        print(f"\n[SERVER INFO]")
        print(f"  Host: {HOST}")
        print(f"  Port: {PORT}")
        print(f"  Connected Users: {user_count}/{MAX_CONNECTIONS}")
        print("> ", end="", flush=True)


# ================= ADMIN INPUT =================
def admin_input():
    """Handle admin commands from stdin"""
    print("\n[ADMIN MODE] Available commands:")
    print("  /list              - List all connected users")
    print("  /kick <username>   - Kick a user")
    print("  /announce <msg>    - Send announcement")
    print("  /info              - Server info")
    print("  /help              - Show this help")
    print()
    
    while True:
        try:
            cmd = input("> ").strip()
            
            if not cmd:
                continue
            
            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            
            if command == "/list":
                AdminTools.list_users()
            
            elif command == "/kick" and len(parts) == 2:
                AdminTools.kick(parts[1])
            
            elif command == "/announce" and len(parts) == 2:
                AdminTools.send_announcement(parts[1])
            
            elif command == "/info":
                AdminTools.server_info()
            
            elif command == "/help":
                print("\nAvailable commands:")
                print("  /list              - List all connected users")
                print("  /kick <username>   - Kick a user")
                print("  /announce <msg>    - Send announcement")
                print("  /info              - Server info")
                print("> ", end="", flush=True)
            
            else:
                print("[ADMIN] Unknown command. Type /help for available commands")
                print("> ", end="", flush=True)
        
        except KeyboardInterrupt:
            print("\n[ADMIN] Shutting down...")
            break
        except Exception as e:
            print(f"[ADMIN ERROR] {e}")


# ================= CLIENT HANDLER =================
def handle_client(conn, addr):
    """Handle individual client connection"""
    print(f"[NEW CONNECTION] {addr} connected")
    
    username = None
    
    try:
        # Receive username with timeout
        conn.settimeout(5.0)
        username_data = conn.recv(MESSAGE_BUFFER_SIZE).decode().strip()
        conn.settimeout(None)
        
        if not username_data:
            print(f"[ERROR] {addr} sent empty username")
            return
        
        username = username_data[:20]  # Limit username length
        
        # Check for duplicate username
        with clients_lock:
            for existing_conn in clients:
                if clients[existing_conn]["username"] == username:
                    broadcast_to_sender(conn, "[SERVER]: Username already taken!")
                    print(f"[ERROR] {addr} tried to use taken username: {username}")
                    return
            
            # Check connection limit
            if len(clients) >= MAX_CONNECTIONS:
                broadcast_to_sender(conn, "[SERVER]: Server is full!")
                print(f"[ERROR] Server full, rejecting {addr}")
                return
            
            clients[conn] = {"username": username, "addr": addr}
        
        # Log and notify
        log_event("JOIN", username, str(addr))
        broadcast(system_msg(username, "JOIN"), exclude_sender=True)
        broadcast_to_sender(conn, "[SERVER]: Welcome to the chat!")
        print(f"[USERNAME] {addr} is {username}")
        
        # Main message loop
        while True:
            message = conn.recv(MESSAGE_BUFFER_SIZE)
            
            if not message:
                break
            
            msg_text = message.decode().strip()
            if msg_text:
                print(f"[{username}] {msg_text}")
                log_event("MESSAGE", username, msg_text)
                broadcast(message, conn, exclude_sender=False)
    
    except socket.timeout:
        print(f"[ERROR] {addr} connection timeout (no username received)")
    
    except Exception as e:
        print(f"[ERROR] {addr} - {type(e).__name__}: {e}")
    
    finally:
        # Cleanup
        with clients_lock:
            if conn in clients:
                username = clients[conn]["username"]
                del clients[conn]
                
                if username:
                    log_event("LEAVE", username, str(addr))
                    broadcast(system_msg(username, "LEAVE"), exclude_sender=True)
        
        try:
            conn.close()
        except:
            pass
        
        print(f"[DISCONNECTED] {username} ({addr})")


# ================= SERVER START =================
def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server.bind((HOST, PORT))
            server.listen(5)
            print(f"[SERVER STARTED] Listening on {HOST}:{PORT}")
            print(f"[INFO] Max connections: {MAX_CONNECTIONS}\n")
            
            # Start admin thread
            admin_thread = threading.Thread(target=admin_input, daemon=True)
            admin_thread.start()
            
            # Accept connections
            while True:
                try:
                    conn, addr = server.accept()
                    client_thread = threading.Thread(
                        target=handle_client,
                        args=(conn, addr),
                        daemon=True
                    )
                    client_thread.start()
                
                except KeyboardInterrupt:
                    print("\n[SERVER] Shutting down...")
                    break
        
        except Exception as e:
            print(f"[FATAL ERROR] {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()