from .database import SessionLocal
from .models import DeviceUser

def check_db():
    db = SessionLocal()
    try:
        devices = db.query(DeviceUser).all()
        print(f"Total devices in database: {len(devices)}")
        
        if devices:
            print("\nDevice details:")
            for device in devices:
                print(f"ID: {device.id}")
                print(f"Name: {device.device_name}")
                print(f"IP: {device.device_ip}")
                print(f"Status: {device.status}")
                print(f"U2 Port: {device.u2_port}")
                print(f"MYT RPC Port: {device.myt_rpc_port}")
                print("-" * 40)
    finally:
        db.close()

if __name__ == "__main__":
    check_db() 
