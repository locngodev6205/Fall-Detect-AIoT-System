const activityNames={
 'event.safe':'Xác nhận người thân an toàn','event.acknowledge':'Tiếp nhận cảnh báo','event.resolve':'Đánh dấu sự kiện đã xử lý','event.false_alarm':'Đánh dấu báo động giả','event.silence':'Tạm tắt âm cảnh báo','event.note':'Thêm ghi chú cho sự kiện',
 'reminder.save':'Lưu lời nhắc','reminder.delete':'Xoá lời nhắc','settings.update':'Cập nhật cài đặt nhà','home.create':'Tạo nhà','home.update':'Cập nhật thông tin nhà','home.archive':'Đưa nhà vào lưu trữ','room.create':'Thêm phòng','room.update':'Đổi tên phòng',
 'camera.claim':'Thêm camera vào nhà','camera.remove':'Gỡ camera khỏi nhà','member.update':'Cập nhật quyền thành viên','member.revoke':'Thu hồi quyền thành viên','invitation.create':'Gửi lời mời tham gia nhà','invitation.accept':'Chấp nhận lời mời','invitation.decline':'Từ chối lời mời','invitation.revoke':'Thu hồi lời mời','asset.delete':'Xoá file đã lưu','command.create':'Gửi yêu cầu đến thiết bị'
};
export const activityLabel=action=>activityNames[action]||'Cập nhật hoạt động trong nhà';
const deliveryNames={pending:['Đang chờ gửi','gray'],sending:['Đang gửi','amber'],accepted:['Dịch vụ đã tiếp nhận','teal'],sent:['Đã gửi','teal'],delivered:['Đã chuyển đến người nhận','teal'],failed:['Chưa gửi được','red'],bounced:['Không gửi được tới người nhận','red'],rejected:['Yêu cầu gửi bị từ chối','red'],complained:['Người nhận đã báo thư rác','amber'],cancelled:['Đã dừng gửi','gray'],unknown:['Chưa xác nhận kết quả','gray']};
export function deliveryLabel(status){const [label,tone]=deliveryNames[status]||deliveryNames.unknown;return {label,tone};}
