extends GutTest
## The main scene's wiring: a --mock instance that cannot listen must not
## drive another process's plant through the port that process owns.

const PORT: int = 15022

var other: ModbusServer


func before_each() -> void:
	other = ModbusServer.new()


func after_each() -> void:
	other.stop()


func _line(args: PackedStringArray) -> Line:
	var line: Line = autofree(Line.new())
	line.setup(args)
	return line


func test_mock_starts_when_listening() -> void:
	var line: Line = _line(PackedStringArray(["--mock", "--port=%d" % PORT]))
	assert_not_null(line.mock)
	line.server.stop()


func test_no_mock_when_port_taken() -> void:
	assert_eq(other.listen(PORT), OK)
	var line: Line = _line(PackedStringArray(["--mock", "--port=%d" % PORT]))
	assert_push_error("cannot listen")
	assert_null(line.mock, "the mock would drive the other instance's plant")
	assert_string_contains(line.status_text(), "mock PLC not started")


func test_parse_args() -> void:
	assert_eq(
		Line.parse_args(PackedStringArray(["--mock", "--port=1502", "plain"])),
		{"mock": "", "port": "1502"}
	)
