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
    requireFact(["success", "failure", "inventory"].indexOf(request.case_name) >= 0, "unknown case");
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
    var deadline = started + 55;
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
            requireFact(typeof result[key] === "string" && result[key].length <= MAX_DATA_CHARS,
                "missing or oversized " + key);
        });
        return {
            schema_version: 1, scope: "utm-guest-execution", uuid: TARGET_UUID,
            nonce: request.nonce, case_name: request.case_name, exited: true,
            exit_code: result.exitCode, signal_code: result.signalCode,
            stdout_base64: result.outputData, stderr_base64: result.errorData,
            polls: polls
        };
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
            return app.execute(vm, {
                at: "/usr/bin/python3", withArguments: ["-I", "-B", "-", "--nonce", request.nonce],
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
    return JSON.stringify(collect(request, nativeAPI(Application("com.utmapp.UTM"),
        function () { return $.NSProcessInfo.processInfo.systemUptime; },
        function (seconds) { delay(seconds); })));
}
