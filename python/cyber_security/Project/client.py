import os
import socket
import threading
import rsa
import struct
from colorama import just_fix_windows_console
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOST = "127.0.0.1"
PORT = 12345
MAX_PACKET_SIZE = 65536
public_key, private_key = rsa.newkeys(2048)

just_fix_windows_console()


# ================= PACKET HELPERS =================

def recv_exact(sock, size):
    """Read exactly size bytes from socket or return None if disconnected."""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def send_packet(sock, payload):
    """Send one length-prefixed packet."""
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def recv_packet(sock, max_size=MAX_PACKET_SIZE):
    """Receive one length-prefixed packet."""
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
    A fresh random nonce is generated for every single message.
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


# ================= RECEIVE THREAD =================

def receive_messages(sock, aes_key):
    """Background thread: continuously receive and print messages from server."""
    while True:
        try:
            message = recv_aes(sock, aes_key)
            if message is None:
                break
            print(f"\n{message}")
            print("> ", end="", flush=True)
        except (ValueError, ConnectionResetError, OSError):
            break
    print("\n[CLIENT] Disconnected from server.")


# ================= MAIN =================

def main():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))

        # --- RSA handshake: exchange public keys ---
        server_key_pem = recv_packet(sock)
        if server_key_pem is None:
            raise ConnectionError("Server closed connection during handshake")
        server_public_key = rsa.PublicKey.load_pkcs1(server_key_pem)
        send_packet(sock, public_key.save_pkcs1("PEM"))

        # --- Receive AES session key (encrypted with our RSA public key) ---
        encrypted_aes_key = recv_packet(sock)
        if encrypted_aes_key is None:
            raise ConnectionError("Server closed connection before sending AES key")
        aes_key = rsa.decrypt(encrypted_aes_key, private_key)

        # --- Send username (now encrypted with AES) ---
        username = input("Enter your username: ").strip()[:20]
        if not username:
            print("[ERROR] Username cannot be empty")
            return
        send_aes(sock, username, aes_key)

        # --- Start receive thread ---
        recv_thread = threading.Thread(
            target=receive_messages, args=(sock, aes_key), daemon=True
        )
        recv_thread.start()

        print("[CLIENT] Connected! Type messages (Ctrl+C to exit):\n")

        # --- Send loop ---
        while True:
            message = input("> ").strip()
            if message:
                try:
                    send_aes(sock, message, aes_key)
                except (ConnectionResetError, BrokenPipeError, OSError):
                    print("[CLIENT] Lost connection to server.")
                    break

    except ConnectionRefusedError:
        print(f"[ERROR] Cannot connect to {HOST}:{PORT}")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        print("[CLIENT] Disconnected")


if __name__ == "__main__":
    main()