import base64

# Example base64 string
base64_str = "SGVsbG8gRGVlcGVuZHJhIQ=="  # "Hello Deependra!"

# Decode base64 to bytes
decoded_bytes = base64.b64decode(base64_str)

# Convert bytes to string (assuming UTF-8 encoding)
decoded_str = decoded_bytes.decode('utf-8')

print(decoded_str)
