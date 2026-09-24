USB_MARKERS = ("usb", "dac", "fiio", "audioquest", "topping", "creative")
OUTPUT_MODES = ("auto", "system", "usb")


def is_usb_audio_device(name):
    value = str(name).casefold()
    return any(marker in value for marker in USB_MARKERS)


def choose_audio_device(devices, mode):
    mode = mode if mode in OUTPUT_MODES else "auto"
    usb_devices = [name for name in devices if is_usb_audio_device(name)]
    if mode in ("auto", "usb") and usb_devices:
        return usb_devices[0]
    return None


def output_mode_label(mode):
    return {
        "auto": "Auto",
        "system": "System / Bluetooth",
        "usb": "USB DAC",
    }.get(mode, "Auto")
