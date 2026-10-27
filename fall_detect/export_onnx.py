"""
Script hỗ trợ chuyển đổi mô hình Fall Detection sang ONNX
Sử dụng:
    python export_onnx.py --input models/fall_detection_transformer.tflite --output models/fall_detection.onnx
"""

import argparse
import os
import sys

def convert_tflite_to_onnx(tflite_path, onnx_path):
    try:
        import tflite2onnx
    except ImportError:
        print("[LỖI] Cần cài đặt: pip install tflite2onnx")
        sys.exit(1)

    print(f"[*] Đang chuyển đổi từ {tflite_path} sang {onnx_path}...")
    tflite2onnx.convert(tflite_path, onnx_path)
    print(f"[THÀNH CÔNG] File ONNX đã được tạo tại: {onnx_path}")

def main():
    parser = argparse.ArgumentParser(description="Convert Fall Detection Model to ONNX")
    parser.add_argument("--input", type=str, default="models/fall_detection_transformer.tflite", help="Path to .tflite or .h5 model")
    parser.add_argument("--output", type=str, default="models/fall_detection.onnx", help="Output .onnx path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[LỖI] Không tìm thấy file: {args.input}")
        sys.exit(1)

    if args.input.endswith(".tflite"):
        convert_tflite_to_onnx(args.input, args.output)
    else:
        print("[THÔNG BÁO] Đối với file Keras (.h5/SavedModel), hãy dùng: python -m tf2onnx.convert --keras <model.h5> --output <model.onnx>")

if __name__ == "__main__":
    main()
