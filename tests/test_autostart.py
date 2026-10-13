from cct import autostart


def test_command_uses_pythonw_and_quotes_paths():
    cmd = autostart.build_command("C:\\Program Files\\Python\\python.exe", "F:\\My Dir\\proj")
    assert cmd.startswith('"C:\\Program Files\\Python\\pythonw.exe" ')
    assert cmd.endswith('run.pyw"')
    assert cmd.endswith('"F:\\My Dir\\proj\\run.pyw"')


def test_command_keeps_pythonw():
    assert autostart.build_command("C:\\x\\pythonw.exe", "C:\\p").startswith('"C:\\x\\pythonw.exe"')
