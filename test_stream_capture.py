import urllib.request
import cv2
import numpy as np

# Read one JPEG frame from /video_feed/utara
stream = urllib.request.urlopen("http://127.0.0.1:5000/video_feed/utara")
bytes_data = b''
for _ in range(50):
    bytes_data += stream.read(1024)
    a = bytes_data.find(b'\xff\xd8')
    b = bytes_data.find(b'\xff\xd9')
    if a != -1 and b != -1:
        jpg = bytes_data[a:b+2]
        img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            cv2.imwrite("scratch_frames/live_stream_frame.jpg", img)
            crop = img[170:320, 10:280]
            cv2.imwrite("scratch_frames/live_stream_crop.jpg", crop)
            print("Successfully captured live stream frame! Shape:", img.shape)
            break
        bytes_data = bytes_data[b+2:]
stream.close()
