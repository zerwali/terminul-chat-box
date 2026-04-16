import socket
import threading
import sys

HOST = "127.0.0.1"
PORT = 12345

def receive_messages(sock):
    """Receive messages from server"""
    while True:
        try:
            message = sock.recv(1024).decode()
            if message:
                print(f"\n{message}")
                print("> ", end="", flush=True)
            else:
                break
        except:
            break

def main():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
        
        # Send username
        username = input("Enter your username: ").strip()[:20]
        sock.sendall(username.encode())
        
        # Start receive thread
        recv_thread = threading.Thread(target=receive_messages, args=(sock,), daemon=True)
        recv_thread.start()
        
        print("[CLIENT] Connected! Type messages (Ctrl+C to exit):\n")
        
        # Send messages
        while True:
            message = input("> ").strip()
            if message:
                sock.sendall(message.encode())
    
    except ConnectionRefusedError:
        print(f"[ERROR] Cannot connect to {HOST}:{PORT}")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        sock.close()
        print("[CLIENT] Disconnected")

if __name__ == "__main__":
    main()