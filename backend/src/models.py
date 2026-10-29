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

class Reset(Token):
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

class Access(Model):
    role: Literal['caregiver','viewer']
    scopes: list[str] = Field(max_length=100)
    rights: dict[Literal['audio','schedules'],bool] = Field(default_factory=dict)
    @model_validator(mode='after')
    def viewer_rights(self):
        if self.role=='viewer' and any(self.rights.values()): raise ValueError('Người xem không có quyền điều khiển')
        return self

class Invite(Email, Access):
    pass

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
    zone_id: str | None = Field(default=None,max_length=128)
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


class DeleteHome(Model):
    confirmation: str = Field(min_length=1,max_length=120)


class TtsPreview(Model):
    text: str = Field(min_length=1,max_length=3000)
