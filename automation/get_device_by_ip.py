import requests
import json
import logging
import urllib.parse
import time
import uuid
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.models import DeviceUser

# --- 配置日志记录，只输出到控制台 ---
logger = logging.getLogger("get_device_by_ip")
# Ensure handlers are not added multiple times if this module is reloaded
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

def fetch_initial_list_from_api(base_url, ip_address):
    """
    Helper function: Fetches the initial list of devices from /get/{ip}.
    Mirrors logic from user's test_api.py.
    """
    api_url = f"{base_url}/dc_api/v1/list/{ip_address}"
    logger.info(f"Fetching initial device list from: {api_url}")
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        logger.info(f"Initial list API request successful, status code: {response.status_code}")
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"Initial list API request failed (HTTP Error): {http_err}")
        logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Initial list API connection error: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Initial list API request timeout: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Initial list API request error: {req_err}")
    except json.JSONDecodeError:
        logger.error(f"Initial list API response not valid JSON. URL: {api_url}, Response: {response.text if 'response' in locals() else 'N/A'}")
    return None

def fetch_detailed_info_from_api(base_url, device_ip, device_name):
    """
    Helper function: Fetches detailed info for a specific device from /get_api_info/{ip}/{name}.
    Mirrors logic from user's test_api.py.
    """
    # URL encode the device_name in case it contains special characters
    encoded_device_name = urllib.parse.quote(device_name)
    api_url = f"{base_url}/get_api_info/{device_ip}/{encoded_device_name}"
    logger.info(f"Fetching detailed info for device '{device_name}' from: {api_url}")
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        logger.info(f"Detailed info API request successful for '{device_name}', status: {response.status_code}")
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"Detailed info API request failed for '{device_name}' (HTTP Error): {http_err}")
        logger.error(f"Response content: {response.text if 'response' in locals() else 'N/A'}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Detailed info API connection error for '{device_name}': {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Detailed info API request timeout for '{device_name}': {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Detailed info API request error for '{device_name}': {req_err}")
    except json.JSONDecodeError:
        logger.warning(f"Detailed info API response for '{device_name}' not valid JSON. URL: {api_url}, Response: {response.text if 'response' in locals() else 'N/A'}")
    return None

def fetch_devices_by_ip(base_url, ip_address):
    """
    Fetches a list of devices and their details using a two-step API call process.
    1. Get initial list from /get/{ip}.
    2. For each device, get detailed info from /get_api_info/{ip}/{name}.
    Then processes this information.
    """
    logger.info(f"Starting two-step device fetch for IP: {ip_address} using base_url: {base_url}")

    initial_data = fetch_initial_list_from_api(base_url, ip_address)

    if not initial_data:
        logger.error(f"Failed to fetch initial device list for IP {ip_address}. Aborting.")
        return []

    all_devices_from_initial_list = []
    if isinstance(initial_data, dict) and "msg" in initial_data and isinstance(initial_data["msg"], list):
        all_devices_from_initial_list = initial_data["msg"]
        logger.info(f"Successfully fetched {len(all_devices_from_initial_list)} devices in initial list for IP {ip_address}.")
    elif isinstance(initial_data, dict) and "data" in initial_data and isinstance(initial_data["data"], list):
        all_devices_from_initial_list = initial_data["data"]
        logger.info(f"Successfully fetched {len(all_devices_from_initial_list)} devices in initial list ('data' key) for IP {ip_address}.")
    elif isinstance(initial_data, list): # Handle case where the root response is the list
        all_devices_from_initial_list = initial_data
        logger.info(f"Successfully fetched {len(all_devices_from_initial_list)} devices in initial list (root is list) for IP {ip_address}.")
    else:
        logger.error(f"Initial device list for IP {ip_address} is not in expected format (dict with 'msg' or 'data' list or a direct list). Data: {initial_data}")
        return []

    if not all_devices_from_initial_list:
        logger.info(f"No devices found in the initial list for IP {ip_address}.")
        return []

    augmented_devices = []
    for device_summary in all_devices_from_initial_list:
        if not isinstance(device_summary, dict):
            logger.warning(f"Skipping non-dictionary item in initial list: {device_summary}")
            continue

        summary_device_name = None
        # Try to get name from "Names", "names", "name"
        for name_key_initial in ["Names", "names", "name"]:
            if name_key_initial in device_summary and device_summary[name_key_initial]:
                summary_device_name = device_summary[name_key_initial]
                break
        
        summary_device_ip = device_summary.get("ip", ip_address) # Fallback to main ip_address if not in summary

        if not summary_device_name:
            logger.warning(f"Skipping device from initial list due to missing 'Names' field: {device_summary}")
            continue
        
        logger.info(f"Processing device from initial list: Name='{summary_device_name}', IP='{summary_device_ip}'")
        
        # Make a copy to augment, preserving original summary data
        current_device_data = device_summary.copy()

        # Fetch detailed information for this device
        # Use summary_device_ip as it might differ from the overall ip_address if API returns devices from other IPs
        detailed_info = fetch_detailed_info_from_api(base_url, summary_device_ip, summary_device_name)
        
        if detailed_info and isinstance(detailed_info, dict) and detailed_info.get("code") == 200 and isinstance(detailed_info.get("msg"), dict):
            logger.info(f"Successfully fetched and processing detailed info for '{summary_device_name}'.")
            # Merge detailed info into current_device_data. Details take precedence.
            for key, value in detailed_info["msg"].items():
                current_device_data[key] = value
        else:
            logger.warning(f"Failed to fetch or parse valid detailed info for '{summary_device_name}'. Proceeding with summary data only.")
            # If detailed info fails, current_device_data remains the summary data

        augmented_devices.append(current_device_data)
        
        # Adding a small delay as in test_api.py, in case of API rate limits
        time.sleep(0.1) # Reduced from 0.5 for potentially faster processing if many devices

    if not augmented_devices:
        logger.info(f"No devices were successfully augmented with details for IP {ip_address}.")
        return []
        
    logger.info(f"Finished fetching and augmenting details for {len(augmented_devices)} devices for IP {ip_address}.")
    
    # --- Start of existing processing logic, now operating on augmented_devices ---
    processed_devices = []
    
    for device in augmented_devices: # Iterating over the list that now contains merged data
        # Ensure device is a dictionary (it should be if it reached here)
        if not isinstance(device, dict):
            logger.error(f"Unexpected non-dict item in augmented_devices list: {device}")
            continue
            
        # Get device base information (consider all possible key names)
        device_name = None
        # Name from detailed info (e.g., from 'RPC' key if it was a dict) or from summary
        for name_key in ["Names", "names", "name", "device_name"]: # "device_name" could be from detailed info
            if name_key in device and device[name_key]:
                if isinstance(device[name_key], str): # Ensure name is a string
                    device_name = device[name_key]
                    break
                elif isinstance(device[name_key], list) and device[name_key]: # Handle if Names is a list
                     device_name = str(device[name_key][0]) # Take first element as string
                     break

        if not device_name: # If no name found from preferred keys, fallback to a generated one
            device_name = f"device-{uuid.uuid4().hex[:8]}"
            logger.warning(f"Device name not found, generated: {device_name} for device data: {device}")
            
        # Get status information
        status = "unknown" # Default status
        for status_key in ["State", "state", "status"]:
            if status_key in device and device[status_key]:
                status = device[status_key]
                break
        
        # Get IP (use device-specific IP from data, fallback to originally passed ip_address)
        device_ip_specific = device.get("ip", ip_address) 
        
        # Get index
        device_index = None
        for index_key in ["index", "device_index", "id"]: # "id" is less likely for index here
            if index_key in device and device[index_key] is not None:
                try:
                    device_index = int(device[index_key]) # Ensure index is an int
                    break
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert index key '{index_key}' value '{device[index_key]}' to int for device {device_name}")
        
        logger.info(f"Processing device for final list: Name='{device_name}', Status='{status}', IP='{device_ip_specific}', Index='{device_index}'")
        
        # Get port information
        adb_port = None
        rpc_port = None
        
        # Try all possible ADB port keys
        for adb_key in ["ADB", "adb", "u2_port", "android_port", "adb_url"]: # Added "adb_url" as a common alternative
            if adb_key in device and device[adb_key]:
                try:
                    val = device[adb_key]
                    if isinstance(val, int):
                        adb_port = val
                        break
                    elif isinstance(val, str):
                        port_str = val.split(':')[-1]
                        if port_str.isdigit():
                            adb_port = int(port_str)
                            logger.info(f"Device {device_name} (API value {val}): Parsed adb_port in get_device_by_ip: {adb_port}")
                            break
                except Exception as e:
                    logger.warning(f"Could not parse ADB port from key '{adb_key}', value '{device[adb_key]}' for device {device_name}: {e}")
                    
        # Try all possible RPC port keys
        # Crucial: "RPC" is the key used in the detailed info from test_api.py
        for rpc_key in ["RPC", "rpc", "rpc_port", "myt_rpc_port", "api_url"]: # Added "api_url"
            if rpc_key in device and device[rpc_key]:
                try:
                    val = device[rpc_key]
                    if isinstance(val, int):
                        rpc_port = val
                        logger.info(f"Device {device_name} (API value {val}): Parsed rpc_port (int) in get_device_by_ip: {rpc_port}")
                        break
                    elif isinstance(val, str):
                        port_str = val.split(':')[-1]
                        if port_str.isdigit():
                            rpc_port = int(port_str)
                            # This is the key log line we added before for RPC, ensure it captures the final parsed port.
                            logger.info(f"Device {device_name} (API value {val}): Parsed rpc_port (str) in get_device_by_ip: {rpc_port}")
                            break
                except Exception as e:
                    logger.warning(f"Could not parse RPC port from key '{rpc_key}', value '{device[rpc_key]}' for device {device_name}: {e}")

        # Fallback for RPC port if not found, e.g. from 'webrtc' or 'ctr_port' (less likely if detailed info is good)
        if not rpc_port:
            for fallback_rpc_key in ["webrtc", "ctr_port"]:
                if fallback_rpc_key in device and device[fallback_rpc_key]:
                    try:
                        val = device[fallback_rpc_key]
                        if isinstance(val, int):
                            rpc_port = val
                            logger.info(f"Device {device_name}: Using fallback RPC port {rpc_port} from key '{fallback_rpc_key}'")
                            break
                        elif isinstance(val, str) and val.isdigit(): # If it's a string but just the port number
                            rpc_port = int(val)
                            logger.info(f"Device {device_name}: Using fallback RPC port {rpc_port} from key '{fallback_rpc_key}' (parsed string)")
                            break
                    except Exception as e:
                         logger.warning(f"Could not parse fallback RPC port from key '{fallback_rpc_key}', value '{val}' for device {device_name}: {e}")
        
        processed_devices.append({
            "name": device_name,
            "status": status,
            "ip": device_ip_specific,
            "adb_port": adb_port,
            "rpc_port": rpc_port,
            "index": device_index
        })
        
        if str(status).lower() == "running":
            logger.info(f"Found running device: {device_name}, IP: {device_ip_specific}, ADB: {adb_port}, RPC: {rpc_port}")
    
    running_devices_count = sum(1 for d in processed_devices if str(d.get("status")).lower() == "running")
    logger.info(f"Total processed devices: {len(processed_devices)}. Running: {running_devices_count}/{len(processed_devices)}.")
    
    return processed_devices
            
if __name__ == "__main__":
    # Example usage (ensure this matches how it's called from routes or other scripts)
    api_base = "http://127.0.0.1:5000" # Example, use actual from env or config
    target_ip = "10.18.96.3"  # Example test IP
    
    # Setup logger for standalone testing if needed
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(ch)
        logger.setLevel(logging.INFO)

    devices_info = fetch_devices_by_ip(api_base, target_ip)
    
    if devices_info:
        print(f"Fetched {len(devices_info)} devices for IP {target_ip}:")
        for dev in devices_info:
            print(f"  Name: {dev['name']}, Status: {dev['status']}, IP: {dev['ip']}, ADB: {dev['adb_port']}, RPC: {dev['rpc_port']}, Index: {dev['index']}")
    else:
        print(f"No devices fetched for IP {target_ip}.") 
