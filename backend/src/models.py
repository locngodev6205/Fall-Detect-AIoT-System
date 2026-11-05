import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)

class Email(Model):
    email: str = Field(min_length=3,max_length=254)
    @field_validator('email')
    @classmethod
    def email_valid(cls,value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('Email không hợp lệ')
        return value.strip().lower()

class Login(Email):
    password: str = Field(min_length=1,max_length=256)
    @field_validator('password', mode='before')
    @classmethod
    def keep_password(cls,value):
        # Passwords are never normalized or stripped.
        return value
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=False)

class Register(Login):
    name: str = Field(min_length=1,max_length=120)
    @field_validator('name')
    @classmethod
    def name_valid(cls,value):
        if not value.strip(): raise ValueError('Nhập họ và tên')
        return value.strip()
    @field_validator('password')
    @classmethod
    def strong(cls,value):
        if len(value)<10: raise ValueError('Mật khẩu cần ít nhất 10 ký tự')
        return value

class Token(Model):
    token: str = Field(min_length=20,max_length=256)

class VerifyEmail(Model):
    token: str | None = Field(default=None,min_length=20,max_length=256)
    code: str | None = Field(default=None,pattern=r'^\d{8}$')

    @model_validator(mode='after')
    def one_verification_credential(self):
        if (self.token is None) == (self.code is None):
            raise ValueError('Nhập mã xác minh hoặc sử dụng liên kết cũ.')
        return self

class ResetCredential(VerifyEmail):
    email: str | None = Field(default=None,max_length=254)

    @model_validator(mode='after')
    def reset_email_required(self):
        if self.code:
            if not self.email: raise ValueError('Nhập email đã yêu cầu đặt lại mật khẩu.')
            self.email=Email(email=self.email).email
        return self

class Reset(ResetCredential):
    password: str = Field(min_length=10,max_length=256)
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=False)

class Home(Model):
    name: str = Field(min_length=1,max_length=120)
    timezone: str = 'Asia/Ho_Chi_Minh'
    @field_validator('timezone')
    @classmethod
    def timezone_valid(cls,value):
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise ValueError('Múi giờ không hợp lệ')
        return value

class Name(Model):
    name: str = Field(min_length=1,max_length=120)

class CameraRights(Model):
    audio: bool = False
    schedules: bool = False

class Access(Model):
    role: Literal['caregiver','viewer','member']
    scopes: list[str] = Field(max_length=100)
    rights: dict[Literal['audio','schedules'],bool] = Field(default_factory=dict)
    camera_permissions: dict[str,CameraRights] = Field(default_factory=dict)
    @model_validator(mode='after')
    def viewer_rights(self):
        if not set(self.camera_permissions).issubset(self.scopes):
            raise ValueError('Quyền từng camera phải nằm trong phạm vi camera được chọn')
        if self.role!='caregiver' and (any(self.rights.values()) or any(any(rights.model_dump().values()) for rights in self.camera_permissions.values())):
            raise ValueError('Người xem không có quyền điều khiển')
        return self

    def rights_for_camera(self,camera_id:str):
        if self.camera_permissions:
            return self.camera_permissions.get(camera_id,CameraRights())
        return CameraRights(**{key:bool(value) for key,value in self.rights.items()})

class Invite(Email, Access):
    role: Literal['caregiver','viewer']

class JoinInvitationCode(Model):
    code: str = Field(min_length=16,max_length=40)

    @field_validator('code')
    @classmethod
    def normalized_code(cls,value):
        from .invitation_codes import normalize,ALPHABET
        value=normalize(value)
        if len(value)!=16 or any(char not in ALPHABET for char in value):
            raise ValueError('Mã mời gồm 16 ký tự. Vui lòng sao chép đúng mã chủ nhà cung cấp.')
        return value

class Claim(Model):
    code: str = Field(min_length=8,max_length=128)
    name: str = Field(min_length=1,max_length=120)
    room_id: str

class Action(Model):
    action: Literal['acknowledge','resolve','safe','false_alarm','note','silence']
    note: str = Field(default='',max_length=2000)
    confirm_abnormal: bool = False

class Reminder(Model):
    camera_id: str
    name: str = Field(min_length=1,max_length=120)
    time: str
    weekdays: list[int] = Field(default_factory=lambda:list(range(7)),max_length=7)
    once_date: date | None = None
    timezone: str = 'Asia/Ho_Chi_Minh'
    enabled: bool = True
    source: Literal['tts','audio'] = 'tts'
    text: str = Field(default='',max_length=3000)
    asset_id: str | None = None
    volume: int = Field(default=70,ge=0,le=100)
    late_seconds: int = Field(default=0,ge=0,le=3600)
    @model_validator(mode='after')
    def valid(self):
        Home.timezone_valid(self.timezone)
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',self.time): raise ValueError('Giờ không hợp lệ')
        if any(x<0 or x>6 for x in self.weekdays) or len(set(self.weekdays))!=len(self.weekdays): raise ValueError('Ngày lặp không hợp lệ')
        if not self.once_date and not self.weekdays: raise ValueError('Chọn ngày lặp hoặc ngày phát một lần')
        if self.source=='tts' and not self.text: raise ValueError('Nhập nội dung lời nhắc')
        if self.source=='audio' and not self.asset_id: raise ValueError('Chọn file âm thanh')
        return self

class Command(Model):
    kind: Literal['play_audio','test_speaker','silence']
    asset_id: str | None = None
    volume: int = Field(default=70,ge=0,le=100)
    ttl_seconds: int = Field(default=60,ge=5,le=300)
    idempotency_key: str = Field(min_length=8,max_length=128)
    @model_validator(mode='after')
    def audio(self):
        if self.kind=='play_audio' and not self.asset_id: raise ValueError('Thiếu âm thanh')
        return self

class Heartbeat(Model):
    observation: Literal['unknown','clear','no_person','occluded','camera_error'] = 'unknown'
    capabilities: dict[Literal['camera','speaker','sensors'],bool] = Field(default_factory=dict)

class ConfigAck(Model):
    version: int = Field(ge=1)
    success: bool
    error: str = Field(default='',max_length=500)

class EventInput(Model):
    event_id: str = Field(min_length=1,max_length=128)
    sequence: int = Field(default=1,ge=1)
    kind: Literal['fall','immobility','environment','device']
    severity: Literal['info','warning','critical']
    observed_at: str
    observation: Literal['suspected','abnormal','recovered','unknown'] = 'suspected'
    reason: str = Field(default='',max_length=1000)
    duration_s: float | None = Field(default=None,ge=0,le=604800)
    config_version: int = Field(default=0,ge=0)
    confidence: float | None = Field(default=None,ge=0,le=1)
    @field_validator('observed_at')
    @classmethod
    def timestamp(cls,value):
        from datetime import datetime
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None: raise ValueError('Thời gian phải có múi giờ')
        return parsed.isoformat()

class SensorValue(Model):
    value: float | None = None
    unit: Literal['C','%','ADC','ppm','lux']
    quality: Literal['valid','error','warming_up'] = 'valid'
    @model_validator(mode='after')
    def valid(self):
        if self.quality=='valid' and self.value is None: raise ValueError('Thiếu giá trị đo')
        return self

class Telemetry(Model):
    message_id: str = Field(min_length=1,max_length=128)
    observed_at: str
    readings: dict[Literal['temperature','humidity','gas','light'],SensorValue]
    @field_validator('observed_at')
    @classmethod
    def timestamp(cls,value): return EventInput.timestamp(value)

    @model_validator(mode='after')
    def metric_units(self):
        units={'temperature':{'C'},'humidity':{'%'},'gas':{'ADC','ppm'},'light':{'lux'}}
        if any(reading.unit not in units[metric] for metric,reading in self.readings.items()):
            raise ValueError('Đơn vị đo không khớp loại cảm biến')
        return self

class CommandAck(Model):
    status: Literal['accepted','executing','executed','failed']
    detail: str = Field(default='',max_length=1000)

class Execution(Model):
    reminder_id: str
    occurrence: str = Field(min_length=1,max_length=200)
    status: Literal['played','failed','skipped']
    detail: str = Field(default='',max_length=1000)

class Settings(Model):
    telegram_enabled: bool = False
    telegram_chat_id: str = Field(default='',max_length=64,pattern=r'^-?\d*$')
    telegram_photos: bool = False
    retention_days: int = Field(default=14,ge=1,le=90)
    temperature_high: float = Field(default=35,ge=-20,le=80)
    temperature_low: float = Field(default=16,ge=-20,le=80)
    humidity_high: float = Field(default=85,ge=0,le=100)
    gas_high: float = Field(default=700,ge=0)
    gas_unit: Literal['ADC','ppm'] = 'ADC'
    environment_hold_seconds: int = Field(default=10,ge=0,le=3600)
    hysteresis: float = Field(default=2,ge=0,le=100)
    @model_validator(mode='after')
    def thresholds(self):
        if self.temperature_low>=self.temperature_high: raise ValueError('Ngưỡng thấp phải nhỏ hơn ngưỡng cao')
        return self

EventKind = Literal['fall','immobility','environment','device']
NotificationSeverity = Literal['info','warning','critical']

class NotificationPolicyUpdate(Model):
    reminder_interval_minutes: int = Field(default=15,ge=5,le=1440)
    max_reminders: int = Field(default=3,ge=0,le=5)

class NotificationChannelPolicy(Model):
    enabled: bool = False
    event_kinds: list[EventKind] = Field(default_factory=lambda:['fall','immobility','environment','device'],min_length=1,max_length=4)
    minimum_severity: NotificationSeverity = 'warning'
    camera_scope_all: bool = True
    camera_ids: list[str] = Field(default_factory=list,max_length=32)
    allow_media: bool = False
    chat_id: str = Field(default='',max_length=64,pattern=r'^-?\d*$')
    clear_destination: bool = False
    @field_validator('event_kinds')
    @classmethod
    def unique_event_kinds(cls,value):
        if len(set(value))!=len(value): raise ValueError('Loại sự kiện không được lặp')
        return value
    @field_validator('camera_ids')
    @classmethod
    def unique_cameras(cls,value):
        if len(set(value))!=len(value): raise ValueError('Camera không được lặp')
        return value

class NotificationRecipientUpdate(Model):
    telegram: NotificationChannelPolicy
    email: NotificationChannelPolicy


class DeleteHome(Model):
    confirmation: str = Field(min_length=1,max_length=120)


class TtsPreview(Model):
    text: str = Field(min_length=1,max_length=3000)
