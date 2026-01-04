from PyQt6.QtGui import QImage, QGuiApplication
import sys

app = QGuiApplication(sys.argv)
img = QImage("icon.png")
if not img.isNull():
    # Scale to standard icon sizes if needed, but saving directly might work if plugin exists
    # QImage save to ICO usually works on Windows
    success = img.save("icon.ico", "ICO")
    if success:
        print("Converted successfully")
    else:
        print("Failed to save icon.ico")
else:
    print("Failed to load icon.png")
