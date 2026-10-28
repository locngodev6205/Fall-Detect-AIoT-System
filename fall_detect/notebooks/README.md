# Danh Sách Notebook Huấn Luyện & Thử Nghiệm (Model Notebooks)

Thư mục này chứa các Jupyter Notebook phục vụ nghiên cứu, huấn luyện và đánh giá các kiến trúc mô hình học sâu nhận diện té ngã dựa trên chuỗi 17 điểm khớp xương MediaPipe BlazePose.

## 🌟 Notebook Chính Thức (Production Training)
* **`01_huan_luyen_transformer_fall_detection_aug.ipynb`** (Khuyên dùng):
  * **Kiến trúc:** Transformer Encoder với cơ chế Spatial-Temporal Self-Attention (3 khối Encoder, 4 Attention Heads, $d_{\text{model}}=64$).
  * **Tiền xử lý:** Chuẩn hóa tọa độ tâm hông (Mid-Hip Centering) và tỉ lệ thân người (Torso Scaling).
  * **Tăng cường dữ liệu:** Tăng cường chuỗi động học (xoay ngẫu nhiên $\pm 15^\circ$, dịch chuyển, co giãn, thêm nhiễu Gaussian jittering).
  * **Quy trình:** Stratified 5-Fold Cross-Validation, Lịch học Polynomial Decay, EarlyStopping theo dõi F1-Macro, Tối ưu ngưỡng kích hoạt ($T^*$), Phân tích sai số FP/FN ra file CSV `error_analysis_report.csv`, và chuyển đổi mô hình sang TensorFlow Lite (`.tflite`, ~313 KB) cho thiết bị biên IoT.
  * **Ngôn ngữ mô tả:** 100% tiếng Việt khoa học, chi tiết và có cấu trúc chặt chẽ.

---

## 📚 Các Notebook Thử Nghiệm & Lịch Sử (Baseline & Experiments)
* **`fall-detection-transformer-aug-v1.ipynb`**: Phiên bản notebook gốc (Kaggle) của mô hình Transformer có Data Augmentation.
* **`fall-detection-transformer-f1-v1.ipynb`**: Thử nghiệm huấn luyện Transformer tối ưu hóa trực tiếp theo hàm mất mát/metric F1-Score.
* **`fall-detection-transformer-seq60.ipynb`**: Thử nghiệm mở rộng cửa sổ trượt lên 60 khung hình (sequence length = 60).
* **`fall-detection-d6-lstm-v1.ipynb`**: Mô hình đường cơ sở Baseline sử dụng mạng LSTM đơn hướng (Uni-directional LSTM).
* **`fall-detection-d6-bi-lstm-v1.ipynb`**: Mô hình đường cơ sở Baseline sử dụng mạng LSTM hai chiều (Bidirectional LSTM).


