import socket
import threading

HOST = "127.0.0.1"
PORT = 12345

clients = {}

class tools:
    def list(clients):
        print('users connected: ')
        for c in clients:
            print(clients[conn])

def system_msg(username, msg_type):
    messages = {
        "DIS": "left the chat",
        "CON": "joined the chat"
    }

    if msg_type in messages:
        print(f"{username} {messages[msg_type]}")

def broadcast(message, sender_conn):
    username = clients[sender_conn]
    full_message = f"[{username}]: {message.decode()}"

    for client in clients:
        if client != sender_conn:
            client.sendall(full_message.encode())

def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected")

    username = conn.recv(1024).decode()
    clients[conn] = username
    print(f"[USERNAME] {addr} is {username}")
    broadcast(system_msg(username, 'CON'))

    try:
        while True:
            message = conn.recv(1024)
            if not message:
                break

            print(f"[{clients[conn]}] {message.decode()}")
            broadcast(message, conn)
    finally:
        clients.remove(conn)
        conn.close()
        print(f"[DISCONNECTED] {addr}")
        broadcast(system_msg(username, 'DIS'))

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen()
    print(f"[SERVER STARTED] {HOST}:{PORT}")

    while True:
        conn, addr = s.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()