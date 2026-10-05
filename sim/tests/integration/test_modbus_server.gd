extends GutTest
## The plant's server over real loopback TCP: requests and the watchdog.

const PORT: int = 15021

var server: ModbusServer
var client: ModbusClient


func before_each() -> void:
	server = ModbusServer.new()
	assert_eq(server.listen(PORT), OK)
	client = ModbusClient.new()
	assert_eq(client.connect_to("127.0.0.1", PORT), OK)


func after_each() -> void:
	client.close()
	server.stop()


func test_master_reads_inputs_and_writes_coils() -> void:
	server.inputs[IoMap.DI_LOW_BEAM] = 1
	var di: PackedByteArray = client.read_discrete_inputs(IoMap.INPUT_COUNT, server.poll)
	assert_eq(di, server.inputs)
	var bits: PackedByteArray = PackedByteArray([1, 0, 1, 0, 1])
	assert_true(client.write_coils(bits, server.poll))
	assert_eq(server.coils, bits)
	assert_eq(server.requests, 2)


func test_watchdog_trips_without_requests() -> void:
	assert_false(server.is_online(), "offline before any master speaks")
	var di: PackedByteArray = client.read_discrete_inputs(IoMap.INPUT_COUNT, server.poll)
	assert_eq(di.size(), IoMap.INPUT_COUNT)
	assert_true(server.is_online())
	server.poll(ModbusServer.WATCHDOG_S / 2.0)
	assert_true(server.is_online(), "still inside the window")
	server.poll(ModbusServer.WATCHDOG_S)
	assert_false(server.is_online())


func test_unanswered_request_times_out_empty() -> void:
	var reply: PackedByteArray = client.request(
		Modbus.read_request(Modbus.FC_READ_COILS, 0, 1), func() -> void: pass
	)
	assert_eq(reply, PackedByteArray(), "nobody polled the server")
