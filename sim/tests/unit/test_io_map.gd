extends GutTest
## The address map: one name per address, addresses dense from 0.


func _dense(count: int) -> Array[int]:
	var out: Array[int] = []
	for i: int in range(count):
		out.append(i)
	return out


func test_every_input_has_one_name() -> void:
	assert_eq(IoMap.INPUT_NAMES.size(), IoMap.INPUT_COUNT)
	var addresses: Array[int] = [
		IoMap.DI_START,
		IoMap.DI_STOP_OK,
		IoMap.DI_ESTOP_OK,
		IoMap.DI_LOW_BEAM,
		IoMap.DI_HIGH_BEAM,
		IoMap.DI_AT_DIVERTER,
		IoMap.DI_DIVERTER_OUT,
		IoMap.DI_DIVERTER_HOME,
		IoMap.DI_MAIN_EXIT,
		IoMap.DI_SIDE_EXIT,
	]
	assert_eq(addresses, _dense(IoMap.INPUT_COUNT))


func test_every_coil_has_one_name() -> void:
	assert_eq(IoMap.COIL_NAMES.size(), IoMap.COIL_COUNT)
	var addresses: Array[int] = [
		IoMap.CO_MAIN_MOTOR,
		IoMap.CO_SIDE_MOTOR,
		IoMap.CO_DIVERTER,
		IoMap.CO_RUN_LAMP,
		IoMap.CO_FAULT_LAMP,
	]
	assert_eq(addresses, _dense(IoMap.COIL_COUNT))


func test_port_needs_no_root() -> void:
	assert_gt(IoMap.PORT, 1023)


## `| DI | 0 | start | ... |` rows of the projects/ table, by kind.
func _readme_names(kind: String) -> PackedStringArray:
	var path: String = ProjectSettings.globalize_path("res://").path_join(
		"../projects/sorting-line/README.md"
	)
	var text: String = FileAccess.get_file_as_string(path)
	assert_false(text.is_empty(), "cannot read %s" % path)
	var names: Array[String] = []
	for line: String in text.split("\n"):
		var cells: PackedStringArray = line.split("|")
		if cells.size() > 4 and cells[1].strip_edges() == kind:
			assert_eq(cells[2].strip_edges().to_int(), names.size(), "%s address order" % kind)
			names.append(cells[3].strip_edges())
	return PackedStringArray(names)


func test_readme_table_matches_inputs() -> void:
	assert_eq(_readme_names("DI"), IoMap.INPUT_NAMES)


func test_readme_table_matches_coils() -> void:
	assert_eq(_readme_names("coil"), IoMap.COIL_NAMES)
