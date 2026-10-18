/* UTM guest result adapter for the I5 preparation inventory only.
 * Original implementation against UTM.sdef and Apple's documented JXA API.
 * --self-test is pure JavaScript: no Application, ObjC or real guest calls.
 * --collect requires separately authorized, already-running isolated VM.
 */
"use strict";

var TARGET_UUID = "B86E1A47-9A67-4ECF-A51F-2B2F29CDB726";
var MAX_DATA_CHARS = 4 * Math.ceil(128 * 1024 / 3);

function requireFact(condition, message) {
    if (!condition) {
        throw new Error(message);
    }
}

function integer(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value;
}

function validateRequest(request) {
    requireFact(request && typeof request === "object" && !Array.isArray(request), "invalid request");
    requireFact(request.schema_version === 1 && request.uuid === TARGET_UUID, "request target/schema mismatch");
    requireFact(typeof request.nonce === "string" && /^[0-9a-f]{32}$/.test(request.nonce), "invalid nonce");
    requireFact(["success", "failure", "inventory", "details", "preparation-apt"].indexOf(request.case_name) >= 0, "unknown case");
    if (request.case_name === "preparation-apt") {
        requireFact(typeof request.manifest_sha256 === "string" && /^[0-9a-f]{64}$/.test(request.manifest_sha256),
            "missing manifest binding");
        requireFact(Object.keys(request).sort().join(",") ===
            "case_name,manifest_sha256,nonce,program_base64,schema_version,uuid", "unknown preparation request field");
    }
    requireFact(typeof request.program_base64 === "string" && request.program_base64.length > 0 &&
        request.program_base64.length <= 64 * 1024 &&
        /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(request.program_base64),
        "invalid or oversized program");
}

function collect(request, api) {
    validateRequest(request);
    var started = api.now();
    // The Python caller enforces 60 seconds including JXA startup and blocked
    // Apple events; leave five seconds for returning/handling diagnostics.
    var deadline = started + (request.case_name === "preparation-apt" ? 600 : 55);
    var polls = 0;
    function remaining() {
        var seconds = deadline - api.now();
        requireFact(seconds > 0, "guest result timeout; caller must shut down VM");
        return seconds;
    }
    var identity = api.identify(Math.min(5, remaining()));
    requireFact(identity.uuid === TARGET_UUID && identity.status === "started", "target VM is not started");
    remaining();
    // Exactly one execute call. Never resubmit on a missing result or timeout.
    var process = api.execute(request, remaining());
    requireFact(process !== null && process !== undefined, "missing guest process handle");
    while (true) {
        var result = api.result(process, Math.min(5, remaining()));
        polls += 1;
        remaining();
        requireFact(result && typeof result === "object" && !Array.isArray(result), "missing result record");
        requireFact(typeof result.exited === "boolean", "missing or invalid exited field");
        if (result.exited === false) {
            api.sleep(Math.min(0.25, remaining()));
            continue;
        }
        requireFact(integer(result.exitCode) && result.exitCode >= 0 && result.exitCode <= 255,
            "missing or invalid exitCode");
        requireFact(integer(result.signalCode) && result.signalCode >= 0, "missing or invalid signalCode");
        ["outputData", "errorData"].forEach(function (key) {
            var limit = request.case_name === "details" ? 4 * Math.ceil(512 * 1024 / 3) : MAX_DATA_CHARS;
            if (request.case_name === "preparation-apt") { limit = 4 * Math.ceil(2 * 1024 * 1024 / 3); }
            requireFact(typeof result[key] === "string" && result[key].length <= limit,
                "missing or oversized " + key);
        });
        var envelope = {
            schema_version: 1, scope: "utm-guest-execution", uuid: TARGET_UUID,
            nonce: request.nonce, case_name: request.case_name, exited: true,
            exit_code: result.exitCode, signal_code: result.signalCode,
            stdout_base64: result.outputData, stderr_base64: result.errorData,
            polls: polls
        };
        if (request.case_name === "preparation-apt") { envelope.manifest_sha256 = request.manifest_sha256; }
        return envelope;
    }
}

function nativeAPI(app, clock, sleeper) {
    var vm = app.virtualMachines.byId(TARGET_UUID);
    return {
        now: clock,
        sleep: sleeper,
        identify: function (timeout) {
            return {uuid: vm.id({timeout: timeout}), status: vm.status({timeout: timeout})};
        },
        execute: function (request, timeout) {
            var args = ["-I", "-B", "-", "--nonce", request.nonce];
            if (request.case_name === "details") { args.push("--details"); }
            if (request.case_name === "preparation-apt") {
                // Public collection is blocked before Application access. Keep
                // the future transport arguments testable without executing.
                args.push("--preparation-apt", "--manifest-sha256", request.manifest_sha256);
            }
            return app.execute(vm, {
                at: "/usr/bin/python3", withArguments: args,
                usingInput: request.program_base64, base64Encoding: true, outputCapturing: true
            }, {timeout: timeout});
        },
        result: function (process, timeout) { return app.getResult(process, {timeout: timeout}); }
    };
}

function selfTest() {
    var count = 0;
    function equal(a, b, message) { requireFact(JSON.stringify(a) === JSON.stringify(b), message); }
    function test(name, body) {
        try { body(); count += 1; } catch (error) { throw new Error(name + ": " + error.message); }
    }
    function request() {
        return {schema_version: 1, uuid: TARGET_UUID, nonce: "a".repeat(32),
            case_name: "inventory", program_base64: "eA=="};
    }
    function done() { return {exited: true, exitCode: 0, signalCode: 0, outputData: "eA==", errorData: ""}; }
    function fixture(results) {
        var state = {clock: 0, calls: 0, polls: 0, handle: {fixture: true}};
        state.api = {
            now: function () { return state.clock; },
            sleep: function (seconds) { state.clock += seconds; },
            identify: function () { return {uuid: TARGET_UUID, status: "started"}; },
            execute: function () { state.calls += 1; return state.handle; },
            result: function (process) {
                requireFact(process === state.handle, "changed process handle");
                var index = Math.min(state.polls++, results.length - 1);
                return results[index];
            }
        };
        return state;
    }
    function rejects(body, text) {
        var message = "";
        try { body(); } catch (error) { message = error.message; }
        requireFact(message.indexOf(text) >= 0, "expected rejection: " + text + "; got: " + message);
    }
    test("wait on same handle, execute once", function () {
        var f = fixture([{exited: false, exitCode: 0, outputData: ""}, {exited: false}, done()]);
        var result = collect(request(), f.api);
        equal([f.calls, f.polls, result.polls, result.stdout_base64], [1, 3, 3, "eA=="], "early return");
    });
    test("nonzero exit preserved", function () {
        var record = done(); record.exitCode = 17; record.errorData = "eQ==";
        equal(collect(request(), fixture([record]).api).exit_code, 17, "lost exit code");
    });
    test("signal preserved", function () {
        var record = done(); record.signalCode = 15;
        equal(collect(request(), fixture([record]).api).signal_code, 15, "lost signal");
    });
    test("no hasExited fallback", function () {
        var record = done(); delete record.exited; record.hasExited = true;
        rejects(function () { collect(request(), fixture([record]).api); }, "exited field");
    });
    ["exited", "exitCode", "signalCode", "outputData", "errorData"].forEach(function (field) {
        test("missing " + field, function () {
            var record = done(); delete record[field];
            rejects(function () { collect(request(), fixture([record]).api); }, "missing");
        });
    });
    [["exited", 1], ["exitCode", false], ["exitCode", -1], ["exitCode", 256],
        ["signalCode", null], ["outputData", null]].forEach(function (change) {
        test("bad type or range " + change, function () {
            var record = done(); record[change[0]] = change[1];
            rejects(function () { collect(request(), fixture([record]).api); }, "missing");
        });
    });
    test("empty final output remains empty for caller rejection", function () {
        var record = done(); record.outputData = "";
        equal(collect(request(), fixture([record]).api).stdout_base64, "", "fabricated output");
    });
    test("oversized output rejected", function () {
        var record = done(); record.outputData = "A".repeat(MAX_DATA_CHARS + 1);
        rejects(function () { collect(request(), fixture([record]).api); }, "oversized");
    });
    test("timeout never resubmits", function () {
        var f = fixture([{exited: false}]);
        rejects(function () { collect(request(), f.api); }, "timeout");
        equal(f.calls, 1, "repeated execute");
    });
    test("late complete response rejected", function () {
        var f = fixture([done()]);
        f.api.result = function () { f.clock = 56; return done(); };
        rejects(function () { collect(request(), f.api); }, "timeout");
    });
    test("transport error propagated", function () {
        var f = fixture([done()]);
        f.api.result = function () { throw new Error("fixture Apple event failure"); };
        rejects(function () { collect(request(), f.api); }, "fixture Apple event failure");
        equal(f.calls, 1, "repeated execute");
    });
    test("stopped VM never executes", function () {
        var f = fixture([done()]); f.api.identify = function () { return {uuid: TARGET_UUID, status: "stopped"}; };
        rejects(function () { collect(request(), f.api); }, "not started");
        equal(f.calls, 0, "executed stopped VM");
    });
    test("wrong target rejected before API", function () {
        var r = request(); r.uuid = "other";
        rejects(function () { collect(r, {}); }, "target/schema");
    });
    test("bad request rejected before API", function () {
        [null, {}, {schema_version: true}].forEach(function (r) {
            rejects(function () { collect(r, {}); }, "request");
        });
    });
    test("native adapter binds exact target, arguments and retained process", function () {
        var handle = {fixture: "retained process"};
        var calls = 0;
        var vm = {id: function () { return TARGET_UUID; }, status: function () { return "started"; }};
        var app = {
            virtualMachines: {byId: function (uuid) { equal(uuid, TARGET_UUID, "wrong target"); return vm; }},
            execute: function (target, options, modifiers) {
                requireFact(target === vm, "wrong VM handle");
                equal(options.at, "/usr/bin/python3", "wrong executable");
                equal(options.withArguments, ["-I", "-B", "-", "--nonce", request().nonce], "wrong arguments");
                equal([options.usingInput, options.base64Encoding, options.outputCapturing], ["eA==", true, true], "wrong IO");
                requireFact(modifiers.timeout > 0 && modifiers.timeout <= 55, "unbounded execute");
                calls += 1; return handle;
            },
            getResult: function (process, modifiers) {
                requireFact(process === handle && modifiers.timeout <= 5, "wrong result call"); return done();
            }
        };
        collect(request(), nativeAPI(app, function () { return 0; }, function () { throw new Error("unexpected wait"); }));
        equal(calls, 1, "wrong execute count");
    });
    test("details limit does not expand old inventory", function () {
        var r = request(); r.case_name = "details";
        var record = done(); record.outputData = "A".repeat(MAX_DATA_CHARS + 4);
        equal(collect(r, fixture([record]).api).case_name, "details", "lost details binding");
        rejects(function () { collect(request(), fixture([record]).api); }, "oversized");
        record.outputData = "A".repeat(4 * Math.ceil(512 * 1024 / 3) + 4);
        rejects(function () { collect(r, fixture([record]).api); }, "oversized");
    });
    test("details native arguments and unknown case rejection", function () {
        var r = request(); r.case_name = "details";
        var app = {virtualMachines: {byId: function () { return {}; }},
            execute: function (vm, options) {
                equal(options.withArguments, ["-I", "-B", "-", "--nonce", r.nonce, "--details"], "details not selected");
            }};
        nativeAPI(app).execute(r, 1);
        r.case_name = "other";
        rejects(function () { collect(r, {}); }, "unknown case");
    });
    test("preparation deadline is separate and never resubmits", function () {
        var r = request(); r.case_name = "preparation-apt"; r.manifest_sha256 = "a".repeat(64);
        var f = fixture([{exited: false}]);
        rejects(function () { collect(r, f.api); }, "timeout");
        equal([f.calls, f.clock], [1, 600], "preparation deadline changed");
        f = fixture([done()]);
        f.api.result = function () { f.clock = 56; return done(); };
        equal(collect(r, f.api).exit_code, 0, "old deadline applied to preparation");
    });
    test("preparation binding and streams remain bounded", function () {
        var r = request(); r.case_name = "preparation-apt";
        rejects(function () { collect(r, {}); }, "manifest binding");
        r.manifest_sha256 = "a".repeat(64); r.extra = true;
        rejects(function () { collect(r, {}); }, "unknown preparation request");
        delete r.extra;
        var record = done(); record.outputData = "A".repeat(4 * Math.ceil(2 * 1024 * 1024 / 3));
        equal(collect(r, fixture([record]).api).case_name, "preparation-apt", "scope lost");
        record.outputData += "AAAA";
        rejects(function () { collect(r, fixture([record]).api); }, "oversized");
    });
    test("preparation failure cannot produce default success", function () {
        var r = request(); r.case_name = "preparation-apt"; r.manifest_sha256 = "a".repeat(64);
        [null, {exited: null}, {exited: true}, {exited: true, exitCode: 0, signalCode: null}].forEach(function (record) {
            rejects(function () { collect(r, fixture([record]).api); }, "missing");
        });
        var f = fixture([done()]);
        f.api.result = function () { throw new Error("lost preparation result"); };
        rejects(function () { collect(r, f.api); }, "lost preparation result");
        equal(f.calls, 1, "repeated execution after result loss");
    });
    return "I5_UTM_RESULT_SELF_TEST_PASS: " + count + " synthetic cases; no application calls";
}

function run(argv) {
    if (argv.length === 1 && argv[0] === "--self-test") {
        return selfTest();
    }
    requireFact(argv.length === 1 && argv[0] === "--collect", "use --self-test or --collect");
    ObjC.import("Foundation");
    var data = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
    requireFact(data.length <= 96 * 1024, "oversized request");
    var text = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
    var request = JSON.parse(text);
    validateRequest(request);
    requireFact(request.case_name !== "preparation-apt", "I5_PREPARATION_ISOLATION_REQUIRED");
    return JSON.stringify(collect(request, nativeAPI(Application("com.utmapp.UTM"),
        function () { return $.NSProcessInfo.processInfo.systemUptime; },
        function (seconds) { delay(seconds); })));
}

// Internal single-operation RPC mapping. No run()/Application path enables it.
// The controller binds RPC source, program digest and this nonce before calls.
function preparationRPC(request, api) {
    var keys = "action,args,manifest_sha256,nonce,schema_version,scope,sequence,uuid";
    requireFact(request && Object.keys(request).sort().join(",") === keys && request.schema_version === 1 &&
        request.scope === "i5-preparation-utm-rpc" && request.uuid === TARGET_UUID &&
        typeof request.nonce === "string" && /^[0-9a-f]{32}$/.test(request.nonce) &&
        typeof request.manifest_sha256 === "string" && /^[0-9a-f]{64}$/.test(request.manifest_sha256) &&
        integer(request.sequence) && request.sequence >= 0, "preparation RPC binding");
    var a = request.args, value;
    function fields(names) { requireFact(a && typeof a === "object" && !Array.isArray(a) &&
        Object.keys(a).sort().join(",") === names, "RPC fields"); }
    function handle(id) { requireFact(integer(id) && id > 0, "RPC handle"); return id; }
    switch (request.action) {
    case "identify": fields(""); value = api.identify(2); break;
    case "open":
        fields("role"); requireFact(a.role === "lease" || a.role === "ack", "mailbox role");
        value = api.open("/run/radishlink-i5-preparation/" + request.nonce + "/control/" + a.role + ".slot",
                         a.role === "lease", 2); handle(value); break;
    case "read": fields("handle"); value = api.read(handle(a.handle), 1024, 2);
        requireFact(typeof value === "string" && value.length <= 1368, "mailbox read limit"); break;
    case "write":
        fields("data,handle"); requireFact(typeof a.data === "string" && a.data.length === 1368 &&
            /^(?:[A-Za-z0-9+/]{4}){341}[A-Za-z0-9+/]{2}==$/.test(a.data), "mailbox write size");
        api.write(handle(a.handle), a.data, 2); value = null; break;
    case "execute":
        fields("program_base64,program_sha256");
        requireFact(typeof a.program_sha256 === "string" && /^[0-9a-f]{64}$/.test(a.program_sha256), "program digest");
        var execution = {schema_version: 1, uuid: TARGET_UUID, nonce: request.nonce, case_name: "preparation-apt",
            manifest_sha256: request.manifest_sha256, program_base64: a.program_base64};
        validateRequest(execution);
        value = api.execute(execution, 2); handle(value); break;
    case "result":
        fields("process"); value = api.result(handle(a.process), 2);
        requireFact(value && typeof value.exited === "boolean", "RPC exited field");
        if (value.exited) {
            requireFact(integer(value.exitCode) && value.exitCode >= 0 && value.exitCode <= 255 &&
                integer(value.signalCode) && value.signalCode >= 0 && typeof value.outputData === "string" &&
                value.outputData.length <= 4 * Math.ceil(2 * 1024 * 1024 / 3) && typeof value.errorData === "string" &&
                value.errorData.length <= 4 * Math.ceil(65536 / 3), "RPC result fields/limit");
            value = {exited: true, exit_code: value.exitCode, signal_code: value.signalCode,
                     stdout_base64: value.outputData, stderr_base64: value.errorData};
        } else { value = {exited: false}; }
        break;
    case "close": fields("handle"); api.close(handle(a.handle), 2); value = null; break;
    default: throw new Error("unknown preparation RPC action");
    }
    return {schema_version: 1, scope: "i5-preparation-utm-rpc-result", uuid: TARGET_UUID, nonce: request.nonce,
            manifest_sha256: request.manifest_sha256, sequence: request.sequence, action: request.action, value: value};
}

function preparationNativeAPI(app) {
    // Documented installed UTM.sdef: reading+updating requires an existing file,
    // explicit offsets/lengths avoid append/truncate or read-until-EOF behavior.
    var vm = app.virtualMachines.byId(TARGET_UUID);
    var execution = nativeAPI(app, function () { throw new Error("clock not used by RPC"); }, function () {});
    return {
        identify: execution.identify,
        open: function (path, writable, timeout) {
            return app.openFile(vm, {at: path, for: "reading", updating: writable}, {timeout: timeout}).id({timeout: timeout});
        },
        read: function (id, length, timeout) {
            return app.read(vm.guestFiles.byId(id), {atOffset: 0, from: "start position", forLength: length,
                base64Encoding: true, closing: false}, {timeout: timeout});
        },
        write: function (id, data, timeout) {
            app.write(vm.guestFiles.byId(id), {withData: data, atOffset: 0, from: "start position",
                base64Encoding: true, closing: false}, {timeout: timeout});
        },
        execute: function (request, timeout) { return execution.execute(request, timeout).id({timeout: timeout}); },
        result: function (id, timeout) { return app.getResult(vm.guestProcesses.byId(id), {timeout: timeout}); },
        close: function (id, timeout) { app.close(vm.guestFiles.byId(id), {timeout: timeout}); }
    };
}

// Internal bounded byte driver. io is injected in pure Node tests. Blocking
// native read/write/Apple events are bounded by the external process deadline,
// never by a promise or an in-process timer. EOF terminates exactly one JSON.
function preparationRPCStream(io, expectedText, makeAPI) {
    requireFact(typeof expectedText === "string", "RPC expected input binding");
    var chunks = [], total = 0, chunk;
    while (true) {
        chunk = io.read(Math.min(65536, 96 * 1024 - total + 1));
        requireFact(chunk && integer(chunk.length) && chunk.length >= 0 &&
            chunk.length <= Math.min(65536, 96 * 1024 - total + 1), "RPC byte read size");
        if (chunk.length === 0) { break; }
        total += chunk.length;
        requireFact(total <= 96 * 1024, "RPC input byte limit");
        chunks.push(chunk);
    }
    var text = io.decode(io.join(chunks));
    requireFact(typeof text === "string" && text === expectedText, "RPC exact stdin binding/UTF8");
    var request = JSON.parse(text);
    var api;
    var deferred = {};
    ["identify", "open", "read", "write", "execute", "result", "close"].forEach(function (name) {
        deferred[name] = function () {
            if (!api) { api = makeAPI(); }
            return api[name].apply(api, arguments);
        };
    });
    var response = preparationRPC(request, deferred);
    var bytes = io.encode(JSON.stringify(response));
    requireFact(bytes && integer(bytes.length) && bytes.length > 0 && bytes.length <= 6 * 1024 * 1024,
        "RPC output byte limit");
    var offset = 0;
    while (offset < bytes.length) {
        var size = Math.min(65536, bytes.length - offset);
        var count = io.write(bytes, offset, size);
        requireFact(integer(count) && count > 0 && count <= size, "RPC byte short/zero write");
        offset += count;
    }
}

function preparationFoundationIO() {
    // ReadDataOfLength bounds allocation per read. No readDataToEndOfFile,
    // shell, argv payload or public run() flag is used by this internal driver.
    ObjC.import("Foundation");
    var input = $.NSFileHandle.fileHandleWithStandardInput;
    var output = $.NSFileHandle.fileHandleWithStandardOutput;
    return {
        read: function (length) { return input.readDataOfLength(length); },
        join: function (chunks) {
            var data = $.NSMutableData.data;
            chunks.forEach(function (chunk) { data.appendData(chunk); });
            return data;
        },
        decode: function (data) {
            var text = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
            requireFact(text && !text.isNil(), "RPC invalid UTF8");
            return text.js;
        },
        encode: function (text) { return $(text).dataUsingEncoding($.NSUTF8StringEncoding); },
        write: function (data, offset, length) {
            output.writeData(data.subdataWithRange($.NSMakeRange(offset, length)));
            return length;
        }
    };
}
