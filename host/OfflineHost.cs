using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace WowRaidAnalyzer
{
    /// <summary>
    /// Zero-dependency Windows host: serves static files and persists scoreboard/data JSON.
    /// End users need no Python — drop analysis JSON into ./data and open the home page.
    /// </summary>
    class Program
    {
        static string Root;
        static string DataDir;
        static string ScoreboardDir;
        static HttpListener Listener;
        const int DefaultPort = 8765;

        static int Main(string[] args)
        {
            Root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            DataDir = Path.Combine(Root, "data");
            ScoreboardDir = Path.Combine(Root, "scoreboard");
            Directory.CreateDirectory(DataDir);
            Directory.CreateDirectory(ScoreboardDir);

            int preferredPort = DefaultPort;
            bool portExplicit = false;
            bool openBrowser = true;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--port" && i + 1 < args.Length)
                {
                    if (int.TryParse(args[++i], out preferredPort)) portExplicit = true;
                }
                if (args[i] == "--no-open") openBrowser = false;
            }

            string prefix = null;
            Exception lastBindError = null;
            int[] candidates = portExplicit
                ? new int[] { preferredPort }
                : BuildPortCandidates(preferredPort);
            foreach (int port in candidates)
            {
                string tryPrefix = "http://127.0.0.1:" + port + "/";
                var listener = new HttpListener();
                listener.Prefixes.Add(tryPrefix);
                try
                {
                    listener.Start();
                    Listener = listener;
                    prefix = tryPrefix;
                    if (port != preferredPort)
                        Console.WriteLine("端口 " + preferredPort + " 已被占用，改用 " + port);
                    break;
                }
                catch (Exception ex)
                {
                    lastBindError = ex;
                    try { listener.Close(); } catch { }
                }
            }
            if (Listener == null || prefix == null)
            {
                Console.Error.WriteLine("无法启动本地服务（端口可能被占用）: " + (lastBindError != null ? lastBindError.Message : "unknown"));
                Console.Error.WriteLine("可尝试: RaidAnalyzer.exe --port 8877");
                Console.Error.WriteLine("按任意键退出...");
                try { Console.ReadKey(true); } catch { }
                return 1;
            }

            Console.WriteLine("========================================");
            Console.WriteLine("  WoW 开荒复盘 · 本地宿主");
            Console.WriteLine("  " + prefix);
            Console.WriteLine("  数据目录: " + DataDir);
            Console.WriteLine("  计分板:   " + ScoreboardDir);
            Console.WriteLine("  关闭本窗口即停止服务");
            Console.WriteLine("========================================");

            if (openBrowser)
            {
                try { Process.Start(new ProcessStartInfo { FileName = prefix, UseShellExecute = true }); }
                catch { }
            }

            while (Listener.IsListening)
            {
                try
                {
                    var ctx = Listener.GetContext();
                    ThreadPool.QueueUserWorkItem(_ => Handle(ctx));
                }
                catch (HttpListenerException) { break; }
                catch (ObjectDisposedException) { break; }
            }
            return 0;
        }

        static int[] BuildPortCandidates(int preferred)
        {
            var ports = new List<int>();
            ports.Add(preferred);
            for (int p = 8766; p <= 8780; p++)
            {
                if (p != preferred) ports.Add(p);
            }
            if (preferred != 8877) ports.Add(8877);
            return ports.ToArray();
        }

        static void Handle(HttpListenerContext ctx)
        {
            try
            {
                var req = ctx.Request;
                var res = ctx.Response;
                string path = Uri.UnescapeDataString(req.Url.AbsolutePath);
                if (string.IsNullOrEmpty(path) || path == "/") path = "/frontend/offline/index.html";

                if (path.StartsWith("/api/", StringComparison.OrdinalIgnoreCase))
                {
                    HandleApi(req, res, path);
                    return;
                }

                // Friendly routes
                if (path.Equals("/report", StringComparison.OrdinalIgnoreCase)) path = "/frontend/report/index.html";
                else if (path.Equals("/scoreboard", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/iq-notebook/index.html";
                else if (path.Equals("/verdict", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/iq-notebook/index.html";
                else if (path.Equals("/loot", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/raid-loot/index.html";
                else if (path.Equals("/recruitment", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/recruitment/index.html";
                else if (path.Equals("/audit", StringComparison.OrdinalIgnoreCase)) path = "/frontend/report/plugins/void_spire/crown_of_the_cosmos/audit.html";
                else if (path.Equals("/cooldowns", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/raid-cooldowns/index.html";
                else if (path.Equals("/raid-guide", StringComparison.OrdinalIgnoreCase)) path = "/frontend/tools/raid-guide/index.html";

                ServeFile(res, path);
            }
            catch (Exception ex)
            {
                try { WriteText(ctx.Response, 500, "text/plain; charset=utf-8", "Internal error: " + ex.Message); }
                catch { }
            }
        }

        static void HandleApi(HttpListenerRequest req, HttpListenerResponse res, string path)
        {
            // GET /api/health
            if (path.Equals("/api/health", StringComparison.OrdinalIgnoreCase))
            {
                WriteJson(res, 200, "{\"ok\":true}");
                return;
            }

            // GET /api/data-files  → labeled catalog for UI switching
            if (path.Equals("/api/data-files", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                var items = new List<string>();
                if (Directory.Exists(DataDir))
                {
                    foreach (var file in Directory.GetFiles(DataDir, "wcl_*.json"))
                    {
                        var info = new FileInfo(file);
                        string web = "data/" + info.Name;
                        items.Add(string.Format(
                            "{{\"path\":{0},\"name\":{1},\"label\":{2},\"size\":{3},\"mtime\":{4}}}",
                            JsonString(web),
                            JsonString(info.Name),
                            JsonString(info.Name),
                            info.Length,
                            (long)(info.LastWriteTimeUtc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds
                        ));
                    }
                }
                // Prefer freshest first (simple string mtime numeric at end — sort client-side)
                WriteJson(res, 200, "{\"schemaVersion\":1,\"files\":[" + string.Join(",", items.ToArray()) + "]}");
                return;
            }

            // GET /api/data/list
            if (path.Equals("/api/data/list", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                var items = new List<string>();
                foreach (var file in Directory.GetFiles(DataDir, "*.json"))
                {
                    var info = new FileInfo(file);
                    items.Add(string.Format(
                        "{{\"path\":{0},\"name\":{1},\"label\":{2},\"size\":{3},\"mtime\":{4}}}",
                        JsonString("data/" + info.Name),
                        JsonString(info.Name),
                        JsonString(info.Name),
                        info.Length,
                        (long)(info.LastWriteTimeUtc - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds
                    ));
                }
                WriteJson(res, 200, "[" + string.Join(",", items.ToArray()) + "]");
                return;
            }

            // GET /api/data/{name}
            var dataMatch = Regex.Match(path, @"^/api/data/([^/]+)$", RegexOptions.IgnoreCase);
            if (dataMatch.Success && req.HttpMethod == "GET")
            {
                string name = SanitizeFileName(dataMatch.Groups[1].Value);
                if (!name.EndsWith(".json", StringComparison.OrdinalIgnoreCase)) name += ".json";
                string full = Path.Combine(DataDir, name);
                if (!File.Exists(full)) { WriteJson(res, 404, "{\"error\":\"not found\"}"); return; }
                WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(full));
                return;
            }

            // Prefer auto file: GET /api/data/latest
            if (path.Equals("/api/data/latest", StringComparison.OrdinalIgnoreCase) && req.HttpMethod == "GET")
            {
                FileInfo latest = null;
                foreach (var file in Directory.GetFiles(DataDir, "*.json"))
                {
                    var info = new FileInfo(file);
                    if (latest == null || info.LastWriteTimeUtc > latest.LastWriteTimeUtc) latest = info;
                }
                if (latest == null) { WriteJson(res, 404, "{\"error\":\"no data json\"}"); return; }
                WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(latest.FullName));
                return;
            }

            // GET /api/notebook|/api/scoreboard  → catalog of days (local diary store)
            if ((path.Equals("/api/scoreboard", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook", StringComparison.OrdinalIgnoreCase)) &&
                req.HttpMethod == "GET")
            {
                var days = new List<string>();
                foreach (var file in Directory.GetFiles(ScoreboardDir, "day-*.json"))
                {
                    string raw = File.ReadAllText(file, Encoding.UTF8);
                    days.Add(raw);
                }
                // Also support store.json multi-day
                string storePath = Path.Combine(ScoreboardDir, "store.json");
                if (File.Exists(storePath))
                {
                    WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(storePath));
                    return;
                }
                WriteJson(res, 200, "{\"schemaVersion\":2,\"days\":[" + string.Join(",", days.ToArray()) + "]}");
                return;
            }

            // GET/PUT/POST/DELETE /api/notebook|scoreboard/{date}
            var sbMatch = Regex.Match(path, @"^/api/(?:scoreboard|notebook)/(\d{4}-\d{2}-\d{2})$", RegexOptions.IgnoreCase);
            if (sbMatch.Success)
            {
                string date = sbMatch.Groups[1].Value;
                string dayFile = Path.Combine(ScoreboardDir, "day-" + date + ".json");
                string storePath = Path.Combine(ScoreboardDir, "store.json");

                if (req.HttpMethod == "GET")
                {
                    if (File.Exists(dayFile))
                    {
                        WriteBytes(res, 200, "application/json; charset=utf-8", File.ReadAllBytes(dayFile));
                        return;
                    }
                    WriteJson(res, 404, "{\"error\":\"day not found\"}");
                    return;
                }

                if (req.HttpMethod == "PUT" || req.HttpMethod == "POST")
                {
                    string body = ReadBody(req);
                    File.WriteAllText(dayFile, body, new UTF8Encoding(false));
                    UpsertStore(storePath, date, body);
                    WriteJson(res, 200, "{\"ok\":true,\"path\":" + JsonString("scoreboard/day-" + date + ".json") + "}");
                    return;
                }

                if (req.HttpMethod == "DELETE")
                {
                    if (File.Exists(dayFile)) File.Delete(dayFile);
                    RemoveFromStore(storePath, date);
                    WriteJson(res, 200, "{\"ok\":true}");
                    return;
                }
            }

            // PUT/POST /api/notebook|/api/scoreboard|/api/*/store  full store replace
            if ((path.Equals("/api/scoreboard", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/scoreboard/store", StringComparison.OrdinalIgnoreCase) ||
                 path.Equals("/api/notebook/store", StringComparison.OrdinalIgnoreCase)) &&
                (req.HttpMethod == "PUT" || req.HttpMethod == "POST"))
            {
                string body = ReadBody(req);
                string storePath = Path.Combine(ScoreboardDir, "store.json");
                File.WriteAllText(storePath, body, new UTF8Encoding(false));
                WriteJson(res, 200, "{\"ok\":true,\"path\":\"scoreboard/store.json\"}");
                return;
            }

            // POST /api/export-verdict-excel  → spawn Python openpyxl exporter when available
            if (path.Equals("/api/export-verdict-excel", StringComparison.OrdinalIgnoreCase))
            {
                if (req.HttpMethod != "POST")
                {
                    WriteJson(res, 405, "{\"error\":\"POST required\"}");
                    return;
                }
                try
                {
                    string body = ReadBody(req);
                    string outPath = ExportVerdictExcelViaPython(body);
                    if (outPath == null || !File.Exists(outPath))
                    {
                        WriteJson(res, 501, "{\"error\":\"xlsx export unavailable (install Python+openpyxl, or use browser VerdictXlsx fallback)\"}");
                        return;
                    }
                    byte[] bytes = File.ReadAllBytes(outPath);
                    res.StatusCode = 200;
                    res.ContentType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
                    // Keep Content-Disposition ASCII-safe; UTF-8 name via filename*.
                    string utfName = Uri.EscapeDataString(Path.GetFileName(outPath));
                    res.Headers.Add("Content-Disposition", "attachment; filename=\"verdict_export.xlsx\"; filename*=UTF-8''" + utfName);
                    res.Headers.Add("Cache-Control", "no-store");
                    res.ContentLength64 = bytes.LongLength;
                    res.OutputStream.Write(bytes, 0, bytes.Length);
                    res.OutputStream.Close();
                }
                catch (Exception ex)
                {
                    WriteJson(res, 500, "{\"error\":" + JsonString(ex.Message) + "}");
                }
                return;
            }

            WriteJson(res, 404, "{\"error\":\"unknown api\"}");
        }

        static string ExportVerdictExcelViaPython(string jsonBody)
        {
            string root = Root;
            string toolsPy = Path.Combine(root, "tools", "export_verdict_excel.py");
            DirectoryInfo dir = new DirectoryInfo(root);
            for (int i = 0; i < 5 && dir != null && !File.Exists(toolsPy); i++, dir = dir.Parent)
                toolsPy = Path.Combine(dir.FullName, "tools", "export_verdict_excel.py");
            if (!File.Exists(toolsPy)) return null;

            string workDir = Path.GetDirectoryName(Path.GetDirectoryName(toolsPy));
            string tempJson = Path.Combine(Path.GetTempPath(), "verdict_export_" + Guid.NewGuid().ToString("N") + ".json");
            string tempOut = Path.Combine(Path.GetTempPath(), "verdict_export_" + Guid.NewGuid().ToString("N") + ".xlsx");
            string tempScript = Path.Combine(Path.GetTempPath(), "verdict_export_" + Guid.NewGuid().ToString("N") + ".py");
            File.WriteAllText(tempJson, jsonBody ?? "{}", new UTF8Encoding(false));
            string script =
                "# -*- coding: utf-8 -*-\n" +
                "import json, sys\n" +
                "from pathlib import Path\n" +
                "sys.path.insert(0, r'''" + workDir + "''')\n" +
                "from tools.export_verdict_excel import export_verdict_excel\n" +
                "payload = json.loads(Path(r'''" + tempJson + "''').read_text(encoding='utf-8'))\n" +
                "out = export_verdict_excel(payload, Path(r'''" + Path.GetDirectoryName(tempOut) + "'''), boss_name='宇宙之冕')\n" +
                "Path(r'''" + tempOut + "''').write_bytes(out.read_bytes())\n" +
                "print(out)\n";
            File.WriteAllText(tempScript, script, new UTF8Encoding(false));

            string[] pyCandidates = new string[]
            {
                Path.Combine(workDir, ".venv", "Scripts", "python.exe"),
                "py",
                "python",
            };

            Exception last = null;
            foreach (string py in pyCandidates)
            {
                if (py.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) && !File.Exists(py)) continue;
                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = py == "py" ? "py" : py,
                        Arguments = (py == "py" ? "-3 " : "") + "\"" + tempScript + "\"",
                        WorkingDirectory = workDir,
                        UseShellExecute = false,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        CreateNoWindow = true,
                    };
                    using (var proc = Process.Start(psi))
                    {
                        string stdout = proc.StandardOutput.ReadToEnd();
                        string stderr = proc.StandardError.ReadToEnd();
                        proc.WaitForExit(120000);
                        if (proc.ExitCode == 0 && File.Exists(tempOut))
                        {
                            try { File.Delete(tempJson); } catch { }
                            try { File.Delete(tempScript); } catch { }
                            return tempOut;
                        }
                        last = new Exception(string.IsNullOrWhiteSpace(stderr) ? stdout : stderr);
                    }
                }
                catch (Exception ex)
                {
                    last = ex;
                }
            }
            try { File.Delete(tempJson); } catch { }
            try { File.Delete(tempOut); } catch { }
            try { File.Delete(tempScript); } catch { }
            if (last != null) throw last;
            return null;
        }

        static void UpsertStore(string storePath, string date, string dayJson)
        {
            string store;
            if (File.Exists(storePath))
            {
                store = File.ReadAllText(storePath, Encoding.UTF8);
                // naive replace/insert of day object by date field
                var re = new Regex("\\{[^{}]*\"date\"\\s*:\\s*\"" + Regex.Escape(date) + "\"[\\s\\S]*?\\}(?=,|\\])", RegexOptions.Multiline);
                if (re.IsMatch(store))
                    store = re.Replace(store, dayJson, 1);
                else
                {
                    int idx = store.LastIndexOf(']');
                    if (idx > 0)
                    {
                        bool empty = store.Substring(0, idx).TrimEnd().EndsWith("[");
                        store = store.Substring(0, idx) + (empty ? dayJson : "," + dayJson) + store.Substring(idx);
                    }
                    else
                        store = "{\"schemaVersion\":2,\"days\":[" + dayJson + "]}";
                }
            }
            else
            {
                store = "{\"schemaVersion\":2,\"days\":[" + dayJson + "]}";
            }
            File.WriteAllText(storePath, store, new UTF8Encoding(false));
        }

        static void RemoveFromStore(string storePath, string date)
        {
            if (!File.Exists(storePath)) return;
            string store = File.ReadAllText(storePath, Encoding.UTF8);
            var re = new Regex(",?\\{[^{}]*\"date\"\\s*:\\s*\"" + Regex.Escape(date) + "\"[\\s\\S]*?\\}", RegexOptions.Multiline);
            store = re.Replace(store, "");
            store = store.Replace("[,", "[").Replace(",]", "]");
            File.WriteAllText(storePath, store, new UTF8Encoding(false));
        }

        static void ServeFile(HttpListenerResponse res, string urlPath)
        {
            string relative = urlPath.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
            if (relative.Contains("..")) { WriteText(res, 403, "text/plain", "forbidden"); return; }
            string full = Path.Combine(Root, relative);
            if (!File.Exists(full))
            {
                WriteText(res, 404, "text/plain; charset=utf-8", "Not found: " + urlPath);
                return;
            }
            string ext = Path.GetExtension(full).ToLowerInvariant();
            string ctype = "application/octet-stream";
            if (ext == ".html") ctype = "text/html; charset=utf-8";
            else if (ext == ".js") ctype = "application/javascript; charset=utf-8";
            else if (ext == ".css") ctype = "text/css; charset=utf-8";
            else if (ext == ".json") ctype = "application/json; charset=utf-8";
            else if (ext == ".png") ctype = "image/png";
            else if (ext == ".svg") ctype = "image/svg+xml";
            else if (ext == ".ico") ctype = "image/x-icon";
            WriteBytes(res, 200, ctype, File.ReadAllBytes(full));
        }

        static string ReadBody(HttpListenerRequest req)
        {
            using (var reader = new StreamReader(req.InputStream, req.ContentEncoding ?? Encoding.UTF8))
                return reader.ReadToEnd();
        }

        static string SanitizeFileName(string name)
        {
            name = Path.GetFileName(name);
            foreach (char c in Path.GetInvalidFileNameChars())
                name = name.Replace(c, '_');
            return name;
        }

        static string JsonString(string s)
        {
            if (s == null) return "null";
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                if (c == '\\') sb.Append("\\\\");
                else if (c == '"') sb.Append("\\\"");
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else if (c == '\t') sb.Append("\\t");
                else sb.Append(c);
            }
            sb.Append('"');
            return sb.ToString();
        }

        static void WriteJson(HttpListenerResponse res, int code, string json)
        {
            WriteText(res, code, "application/json; charset=utf-8", json);
        }

        static void WriteText(HttpListenerResponse res, int code, string ctype, string text)
        {
            WriteBytes(res, code, ctype, Encoding.UTF8.GetBytes(text ?? ""));
        }

        static void WriteBytes(HttpListenerResponse res, int code, string ctype, byte[] body)
        {
            res.StatusCode = code;
            res.ContentType = ctype;
            res.ContentEncoding = Encoding.UTF8;
            res.Headers.Add("Cache-Control", "no-store");
            res.ContentLength64 = body.LongLength;
            res.OutputStream.Write(body, 0, body.Length);
            res.OutputStream.Close();
        }
    }
}
