import socket
import threading

HOST = "127.0.0.1"
PORT = 12345

def receive_messages(sock):
    while True:
        try:
            message = sock.recv(1024)
            if not message:
                print("Server closed connection.")
                break
            print("\n" + message.decode())
        except:
            break

def send_messages(sock):
    while True:
        try:
            msg = input()
            if msg.lower() == "exit":  # type "exit" to quit
                sock.close()
                break
            sock.sendall(msg.encode())

        except (KeyboardInterrupt, OSError):
            print("Disconnected from server.")
            break

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))

    print("Connected to chat!")
    username = input("type your username: ")
    s.sendall(username.encode())

    threading.Thread(target=receive_messages, args=(s,), daemon=True).start()

    send_messages(s)