using System;
using System.Diagnostics;
using System.IO;
using Microsoft.Win32;

namespace XXAR.Setup
{
    // Everything the wizard needs to decide its flow, resolved once at startup.
    public class SetupContext
    {
        public string ExePath;
        public long PayloadOffset = -1;
        public string PayloadVersion;

        public string InstalledLocation;
        public string InstalledVersion;

        public string TargetDir;
        public bool PurgeUserData;
        public bool RepairRequested;

        public bool Cancelled;
        public string FailureText;

        public bool HasPayload => PayloadOffset > 0;
        public bool IsInstalled => InstalledLocation != null;
        public bool UninstallOnly { get; private set; }

        public static string DefaultInstallDir =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "XXAR");

        public static SetupContext Detect(bool forceUninstall)
        {
            var ctx = new SetupContext();
            ctx.ExePath = Process.GetCurrentProcess().MainModule.FileName;
            ctx.PayloadOffset = PayloadReader.FindPayloadOffset(ctx.ExePath);
            if (ctx.PayloadOffset > 0)
                ctx.PayloadVersion = PayloadReader.ReadPayloadVersion(ctx.ExePath, ctx.PayloadOffset) ?? "";

            using (var key = Registry.CurrentUser.OpenSubKey(@"Software\XXAR"))
            {
                var location = key?.GetValue("InstallLocation") as string;
                if (!string.IsNullOrEmpty(location)
                    && File.Exists(Path.Combine(location, "resources", "XXAR.exe")))
                {
                    ctx.InstalledLocation = location.TrimEnd('\\') + "\\";
                    ctx.InstalledVersion = key.GetValue("Version") as string;
                }
            }

            ctx.UninstallOnly = forceUninstall || !ctx.HasPayload;
            ctx.TargetDir = (ctx.InstalledLocation ?? DefaultInstallDir).TrimEnd('\\');

            SetupLog.Info($"exe={ctx.ExePath} payload={(ctx.HasPayload ? "yes" : "no")} v={ctx.PayloadVersion} " +
                          $"installed={(ctx.IsInstalled ? ctx.InstalledLocation + " v" + ctx.InstalledVersion : "no")}");
            return ctx;
        }
    }
}
