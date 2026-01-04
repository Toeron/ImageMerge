# Historical Image Aligner

A powerful desktop application for aligning historical photos with modern day recreations. This tool allows you to manually correct perspective and lens distortion differences between two images using advanced warping techniques.

## Features

### 🛠️ Advanced Warping Methods
*   **Perspective (Rigid)**: Uses Homography to align planar surfaces. Best for flat scenes or simple perspective shifts.
*   **TPS (Elastic)**: Uses **Thin Plate Spline** warping. This acts like a "rubber sheet", allowing for non-linear deformations. Best for aligning images with different lens distortions (e.g., Fish-eye vs. Rectlinear) or complex 3D depth.

### ✍️ Versatile Input Tools
*   **Points [•]**: Click to match specific features (e.g., a statue, a door handle).
*   **Lines [/]**: Draw lines along matching edges (e.g., rooflines, curbs).
    *   *Usage*: Draw the line in the same direction in both images (Start->End).
    *   *Editing*: Drag the endpoints (nodes) to adjust position.
*   **Faces [□]**: Define planar regions (e.g., windows, signs, walls).
    *   *Usage*: Drag to create a box, then adjust individual corners to match perspective.
    *   *Constraint*: Each face acts as 4 locked points (TL, TR, BR, BL).

### 💾 Project Persistence
*   **Save Project**: Save your work (Image paths + all points/lines/faces) to a `.json` file.
*   **Load Project**: Restore your session exactly where you left off.

### 🔍 Visualization
*   **Comparison Slider**: Drag a slider to reveal the difference between the Historical and Warped Modern image.
*   **Ghost Mode**: Overlay images with transparency.
*   **Diff Mode**: Highlight pixel differences.
*   **Zoom & Pan**: Mouse wheel to zoom, Middle-click (or hold Space) to pan.

## Installation

### Windows 🪟

1.  **Install Python**: Ensure you have Python 3.9+ installed. [Download Here](https://www.python.org/downloads/).
2.  **Clone the Repository** (or download zip):
    ```powershell
    git clone https://github.com/Toeron/ImageMerge.git
    cd ImageMerge
    ```
3.  **Create a Virtual Environment** (Recommended):
    ```powershell
    python -m venv venv
    .\venv\Scripts\activate
    ```
4.  **Install Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```

### Linux 🐧

1.  **Install System Dependencies**:
    You may need `python3-venv` and OpenGL libraries for OpenCV.
    ```bash
    sudo apt update
    sudo apt install python3-pip python3-venv libgl1
    ```
2.  **Clone the Repository**:
    ```bash
    git clone https://github.com/Toeron/ImageMerge.git
    cd ImageMerge
    ```
3.  **Setup Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
4.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *Dependencies include: `PyQt6`, `opencv-python`, `numpy`*

## Usage

1.  **Launch the App**:
    ```bash
    python main.py
    ```
2.  **Load Images**:
    *   Click **Load Historical (A)**.
    *   Click **Load Modern (B)**.
3.  **Add Correspondences**:
    *   Use the **Input Tool** panel to select Points, Lines, or Faces.
    *   Mark the same features in both images.
4.  **Warp**:
    *   The app calculates alignment automatically once enough points are added (4+).
    *   Switch between **Perspective** and **TPS** to see which result is better.
5.  **Export**:
    *   Click **Save Warped Result** to save the aligned Modern image.
