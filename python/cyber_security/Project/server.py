import os
import socket
import threading
import random
import rsa
import struct
from colorama import Fore, Style, just_fix_windows_console
from pathlib import Path
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOST = "127.0.0.1"
PORT = 12345
MAX_CONNECTIONS = 50
MAX_PACKET_SIZE = 65536  # increased: AES-GCM has no message size limit
public_key, private_key = rsa.newkeys(2048)

clients = {}
clients_lock = threading.Lock()
shutdown_event = threading.Event()

# Enable ANSI color support in Windows terminals (PowerShell/CMD).
just_fix_windows_console()

# ================= PACKET HELPERS =================
def recv_exact(sock, size):
    """Read exactly size bytes from the socket or return None if disconnected."""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def send_packet(sock, payload):
    """Send a length-prefixed payload."""
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)

def recv_packet(sock, max_size=MAX_PACKET_SIZE):
    """Receive one length-prefixed payload."""
    header = recv_exact(sock, 4)
    if header is None:
        return None
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > max_size:
        raise ValueError(f"Invalid packet size: {size}")
    return recv_exact(sock, size)

# ================= AES-GCM ENCRYPTION =================
def send_aes(sock, message: str, aes_key: bytes):
    """Encrypt message with AES-GCM and send.
    Packet layout: [12-byte nonce][ciphertext]
    A fresh random nonce is generated for every message.
    """
    nonce = os.urandom(12)
    ct = AESGCM(aes_key).encrypt(nonce, message.encode("utf-8"), None)
    send_packet(sock, nonce + ct)

def recv_aes(sock, aes_key: bytes):
    """Receive and decrypt one AES-GCM packet."""
    packet = recv_packet(sock)
    if packet is None:
        return None
    nonce, ct = packet[:12], packet[12:]
    return AESGCM(aes_key).decrypt(nonce, ct, None).decode("utf-8")

# ================= LOGGING =================
def log_event(event_type, username="", extra=""):
    """Log events to file for audit trail."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chatlog_file = Path("chat_log.txt")
    eventlog_file = Path("event_log.txt")
    if event_type in ("MESSAGE", "ANNOUNCEMENT"):
        with open(chatlog_file, "a") as f:
            line = f"[{timestamp}] {event_type}: {username}"
            f.write(line + (f" - {extra}\n" if extra else "\n"))
    else:
        with open(eventlog_file, "a") as f:
            line = f"[{timestamp}] {event_type}: {username}"
            f.write(line + (f" - {extra}\n" if extra else "\n"))

# ================= SYSTEM MESSAGES =================
def system_msg(username, msg_type):
    """Generate formatted system messages."""
    messages = {
        "JOIN": "joined the chat",
        "LEAVE": "left the chat",
        "KICK": "was kicked from the chat",
        "ANNOUNCEMENT": "announce",
    }
    if msg_type in messages:
        return f"{Fore.GREEN}[SERVER]: {username} {messages[msg_type]}{Style.RESET_ALL}"
    return f"{Fore.GREEN}[SERVER]: {msg_type}{Style.RESET_ALL}"

def announcement_banner(message):
    """Create a bordered announcement."""
    clean_msg = str(message).strip() or "(empty announcement)"
    event = " [ANNOUNCEMENT] "
    content = f"{clean_msg} "
    width = max(len(content), 60)
    border = "=" * width
    return (
        f"{Fore.YELLOW}{Style.BRIGHT}{border}\n"
        f"{Fore.RED}{Style.BRIGHT}{event}{Style.RESET_ALL}{content.center(width)}\n"
        f"{Fore.YELLOW}{Style.BRIGHT}{border}{Style.RESET_ALL}"
    )

# ================= BOT =================
def bot_message(msg_type):
    """Simple bot responses."""
    if msg_type == "time":
        return f"the time is: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    elif msg_type == "joke":
        jokes = [
            "Why do programmers hate nature? Too many bugs.",
            'I told my computer I needed a break. It said: "No problem, I\'ll go to sleep."',
            "Why don't skeletons fight each other? They don't have the guts.",
            "I tried to catch fog yesterday. Mist!",
        ]
        return random.choice(jokes)
    elif msg_type == "pp":
        return f"your pp size is {random.randint(1, 18)}"

# ================= BROADCAST =================
def broadcast(message, sender_conn=None, exclude_sender=True):
    """Send an encrypted message to all connected clients."""
    with clients_lock:
        recipients = [
            (conn, info["aes_key"])
            for conn, info in clients.items()
            if not (exclude_sender and conn == sender_conn)
        ]

    dead_clients = []
    for conn, aes_key in recipients:
        try:
            send_aes(conn, message, aes_key)
        except (ConnectionResetError, BrokenPipeError, OSError, ValueError):
            dead_clients.append(conn)

    if dead_clients:
        with clients_lock:
            for conn in dead_clients:
                clients.pop(conn, None)
                try:
                    conn.close()
                except OSError:
                    pass

def broadcast_to_sender(conn, message, aes_key=None):
    """Send an encrypted message only to the specified client."""
    if aes_key is None:
        with clients_lock:
            info = clients.get(conn)
            aes_key = info["aes_key"] if info else None
    if aes_key is None:
        return
    try:
        send_aes(conn, message, aes_key)
    except (ConnectionResetError, BrokenPipeError, OSError, ValueError):
        pass

# ================= PRIVATE MESSAGING =================
def find_client_by_username(username):
    """Find a connected client socket by username."""
    with clients_lock:
        for conn, info in clients.items():
            if info["username"] == username:
                return conn
    return None

def private_message(sender, receiver_conn, message):
    """Send a private message to a specific client."""
    with clients_lock:
        target_info = clients.get(receiver_conn)
    if not target_info:
        return
    try:
        send_aes(receiver_conn, f"[PM FROM {sender}] {message}", target_info["aes_key"])
    except Exception as e:
        print(f"{Fore.RED}[ERROR] PM to {target_info['username']}: {e}")

# ================= ADMIN TOOLS =================

class AdminTools:

    @staticmethod
    def list_users():
        with clients_lock:
            if not clients:
                print(f"\n{Fore.MAGENTA}[ADMIN]{Style.RESET_ALL} No users connected")
                return
            print(f"\n{Fore.MAGENTA}[ADMIN]{Style.RESET_ALL} Connected users:")
            for i, (conn, info) in enumerate(clients.items(), 1):
                print(f"  {i}. {info['username']:15} | {info['addr'][0]}:{info['addr'][1]}")
        print("> ", end="", flush=True)

    @staticmethod
    def kick(target_username):
        kicked_conn = None
        kicked_addr = None
        with clients_lock:
            for conn in list(clients):
                if clients[conn]["username"] == target_username:
                    kicked_conn = conn
                    kicked_addr = clients[conn]["addr"]
                    del clients[conn]
                    break
        if kicked_conn is not None:
            log_event("KICK", target_username, str(kicked_addr))
            broadcast(system_msg(target_username, "KICK"))
            try:
                kicked_conn.close()
            except OSError:
                pass
            print(f"[ADMIN] Kicked {target_username} successfully")
        else:
            print(f"[ADMIN] User '{target_username}' not found")

    @staticmethod
    def send_announcement(message):
        announcement = announcement_banner(message)
        broadcast(announcement)
        log_event("ANNOUNCEMENT", "ADMIN", message)
        print(f"{Fore.MAGENTA}{Style.BRIGHT}[ADMIN]{Style.RESET_ALL} Announcement sent")
        print(announcement)

    @staticmethod
    def server_info():
        with clients_lock:
            user_count = len(clients)
        print(f"\n{Fore.CYAN}[SERVER INFO]{Style.RESET_ALL}")
        print(f"  Host: {HOST}")
        print(f"  Port: {PORT}")
        print(f"  Connected users: {user_count}/{MAX_CONNECTIONS}")
        print("> ", end="", flush=True)

    @staticmethod
    def server_shutdown():
        shutdown_event.set()
        print("Disconnecting clients...")
        with clients_lock:
            active_connections = list(clients.keys())
        broadcast("[SERVER]: Server is shutting down")
        for conn in active_connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        with clients_lock:
            for conn in active_connections:
                clients.pop(conn, None)
        print("All clients disconnected.")
        print("Server shut down.")

# ================= ADMIN INPUT =================
def admin_input():
    """Handle admin commands from stdin."""
    print(f"\n{Fore.GREEN}[ADMIN MODE]{Style.RESET_ALL} Available commands:")
    print("  /list              - List all connected users")
    print("  /kick <username>   - Kick a user")
    print("  /announce <msg>    - Send announcement")
    print("  /info              - Server info")
    print("  /shutdown          - Shutdown server")
    print("  /help              - Show this help\n")

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
            elif command == "/shutdown":
                AdminTools.server_shutdown()
                break
            elif command == "/help":
                print("\n  /list /kick <u> /announce <msg> /info /shutdown")
                print("> ", end="", flush=True)
            else:
                print("[ADMIN] Unknown command. Type /help")
                print("> ", end="", flush=True)

        except KeyboardInterrupt:
            print("\n[ADMIN] Shutting down...")
            break
        except Exception as e:
            print(f"[ADMIN ERROR] {e}")

# ================= CLIENT HANDLER =================
def handle_client(conn, addr, aes_key):
    """Handle one connected client for its entire session."""
    print(f"{Fore.CYAN}[NEW CONNECTION]{Style.RESET_ALL} {addr} connected")
    username = None
    ip = addr[0]

    try:
        # --- Receive username ---
        conn.settimeout(5.0)
        username_data = recv_aes(conn, aes_key)
        conn.settimeout(None)

        if not username_data:
            print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {addr} sent empty username")
            return

        username = username_data.strip()[:20]

        # --- Validate username ---
        with clients_lock:
            for info in clients.values():
                if info["username"] == username:
                    send_aes(conn, "[SERVER]: Username already taken!", aes_key)
                    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {addr} tried taken username: {username}")
                    return

            if len(clients) >= MAX_CONNECTIONS:
                send_aes(conn, "[SERVER]: Server is full!", aes_key)
                print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} Server full, rejecting {addr}")
                return

            clients[conn] = {"username": username, "addr": addr, "aes_key": aes_key}

        log_event("JOIN", username, str(addr))
        broadcast(system_msg(username, "JOIN"), sender_conn=conn, exclude_sender=True)
        broadcast_to_sender(conn, "[SERVER]: Welcome to the chat!")
        print(f"{Fore.GREEN}[USERNAME]{Style.RESET_ALL} {addr} is {username}")

        # --- Main message loop ---
        while True:
            msg_text = recv_aes(conn, aes_key)
            if msg_text is None:
                break

            msg_text = msg_text.strip()
            if not msg_text:
                continue

            if msg_text.startswith("/pm "):
                parts = msg_text.split(maxsplit=2)
                if len(parts) < 3:
                    broadcast_to_sender(conn, "[SERVER]: Usage: /pm <username> <message>")
                    continue
                target_username, private_text = parts[1], parts[2]
                target_conn = find_client_by_username(target_username)
                if target_conn is None:
                    broadcast_to_sender(conn, f"[SERVER]: User '{target_username}' not found")
                    continue
                private_message(username, target_conn, private_text)
                broadcast_to_sender(conn, f"[SERVER]: PM sent to {target_username}")
                log_event("MESSAGE", username, f"PM to {target_username}: {private_text}")

            elif msg_text.startswith("/bot"):
                parts = msg_text.split(maxsplit=1)
                if len(parts) < 2 or parts[1].strip().lower() not in ("joke", "time", "pp"):
                    broadcast_to_sender(conn, "[SERVER]: Usage: /bot <joke|time|pp>")
                    continue
                bot_type = parts[1].strip().lower()
                broadcast_to_sender(conn, f"[BOT]: {bot_message(bot_type)}")
                log_event("MESSAGE", "BOT", f"Reply to {username}: {bot_type}")

            else:
                print(f"[{username}] {msg_text}")
                log_event("MESSAGE", username, msg_text)
                broadcast(f"[{username}]: {msg_text}", sender_conn=conn, exclude_sender=False)

    except socket.timeout:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {addr} timed out (no username received)")
    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {addr} — {type(e).__name__}: {e}")
    finally:
        leave_message = None
        with clients_lock:
            if conn in clients:
                username = clients[conn]["username"]
                del clients[conn]
                if username:
                    log_event("LEAVE", username, str(addr))
                    leave_message = system_msg(username, "LEAVE")

        if leave_message:
            broadcast(leave_message, exclude_sender=True)

        try:
            conn.close()
        except OSError:
            pass

        print(f"{Fore.YELLOW}[DISCONNECTED]{Style.RESET_ALL} {username} ({addr})")


# ================= SERVER START =================
def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((HOST, PORT))
            server.listen(5)
            server.settimeout(1.0)
            print(f"{Fore.GREEN}[SERVER STARTED]{Style.RESET_ALL} Listening on {HOST}:{PORT}")
            print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} Max connections: {MAX_CONNECTIONS}\n")

            admin_thread = threading.Thread(target=admin_input, daemon=True)
            admin_thread.start()

            while not shutdown_event.is_set():
                try:
                    conn, addr = server.accept()
                    print(f"{Fore.CYAN}[TCP CONNECT]{Style.RESET_ALL} {addr} accepted, starting handshake")
                except socket.timeout:
                    continue
                except KeyboardInterrupt:
                    print("\n[SERVER] Shutting down...")
                    AdminTools.server_shutdown()
                    break

                try:
                    conn.settimeout(8.0)
                    # --- RSA handshake: exchange public keys ---
                    send_packet(conn, public_key.save_pkcs1("PEM"))
                    peer_key_packet = recv_packet(conn)
                    if peer_key_packet is None:
                        print(f"{Fore.YELLOW}[HANDSHAKE]{Style.RESET_ALL} {addr} closed before sending public key")
                        conn.close()
                        continue
                    peer_public_key = rsa.PublicKey.load_pkcs1(peer_key_packet)

                    # --- Generate AES session key and send it RSA-encrypted ---
                    aes_key = os.urandom(32)                          # 256-bit AES key
                    encrypted_aes_key = rsa.encrypt(aes_key, peer_public_key)
                    send_packet(conn, encrypted_aes_key)
                    conn.settimeout(None)
                    print(f"{Fore.GREEN}[HANDSHAKE OK]{Style.RESET_ALL} {addr}")

                    # --- Spawn client thread ---
                    client_thread = threading.Thread(
                        target=handle_client,
                        args=(conn, addr, aes_key),
                        daemon=True,
                    )
                    client_thread.start()

                except Exception as e:
                    print(f"{Fore.RED}[HANDSHAKE ERROR]{Style.RESET_ALL} {addr}: {e}")
                    try:
                        conn.close()
                    except OSError:
                        pass

        except Exception as e:
            print(f"{Fore.RED}[FATAL ERROR]{Style.RESET_ALL} {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()