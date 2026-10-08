from PIL import Image
import os

source_path = r"C:\Users\Lenovo\StudioProjects\mentor_connect_app\assets\images\wes_logo.jpg"
img = Image.open(source_path)

res_folder = r"C:\Users\Lenovo\StudioProjects\mentor_connect_app\android\app\src\main\res"

sizes = {
    "mipmap-mdpi": (48, 48),
    "mipmap-hdpi": (72, 72),
    "mipmap-xhdpi": (96, 96),
    "mipmap-xxhdpi": (144, 144),
    "mipmap-xxxhdpi": (192, 192),
}

for folder, size in sizes.items():
    folder_path = os.path.join(res_folder, folder)
    os.makedirs(folder_path, exist_ok=True)
    resized_img = img.resize(size, Image.Resampling.LANCZOS)
    target_path = os.path.join(folder_path, "ic_launcher.png")
    resized_img.save(target_path, "PNG")
    print(f"Generated {target_path} ({size[0]}x{size[1]})")

print("Launcher icons generated successfully!")
