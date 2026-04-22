using System;
using System.IO;
using WixSharp;
using WixSharp.CommonTasks;
using WixSharp.Controls;

namespace XXAR.Installer
{
    /// <summary>
    /// Build entry point. Produces dist/XXAR-Installer-v&lt;version&gt;.msi.
    ///
    /// Usage (from repo root):
    ///   dotnet run --project installer_ws -- --version 0.7.0 \
    ///              --bin-dir dist\XXAR --updater-dir dist\Updater \
    ///              --output-dir dist
    /// </summary>
    public class Setup
    {
        // Fixed GUID — must stay stable across versions for upgrade to work.
        private static readonly Guid UpgradeCode = new Guid("7F4E2C9A-8B3D-4A1F-9C62-1E5B3D8A7F01");

        public static int Main(string[] args)
        {
            var opts = Options.Parse(args);

            if (!Directory.Exists(opts.BinDir))
                throw new DirectoryNotFoundException($"Bin source not found: {opts.BinDir}");
            if (!Directory.Exists(opts.UpdaterDir))
                throw new DirectoryNotFoundException($"Updater source not found: {opts.UpdaterDir}");

            var appExe = Path.Combine(opts.BinDir, "XXAR.exe");
            if (!System.IO.File.Exists(appExe))
                throw new FileNotFoundException($"XXAR.exe missing in {opts.BinDir}", appExe);

            var licencePath = Path.GetFullPath(@"installer_ws\License.rtf");
            if (!System.IO.File.Exists(licencePath))
                throw new FileNotFoundException($"License file missing: {licencePath}");

            var project = new ManagedProject("XXAR")
            {
                UpgradeCode = UpgradeCode,
                Version = new Version(opts.Version),
                LicenceFile = licencePath,
                // Per-user install root: %APPDATA%\XXAR\
                Scope = InstallScope.perUser,
                OutDir = opts.OutputDir,
                OutFileName = $"XXAR-Installer-v{opts.Version}",
                Platform = Platform.x64,
                MajorUpgrade = new MajorUpgrade
                {
                    DowngradeErrorMessage = "A newer version of XXAR is already installed.",
                    AllowSameVersionUpgrades = true,
                },
                Dirs = new[]
                {
                    new Dir(@"%AppDataFolder%\XXAR",
                        // Resources\Bin\  — all files under dist\XXAR
                        new Dir("Resources",
                            new Dir(new Id("BIN_DIR"), "Bin", new Files(Path.Combine(opts.BinDir, "*.*"))),
                            new Dir(new Id("UPDATER_DIR"), "Updater", new Files(Path.Combine(opts.UpdaterDir, "*.*")))),
                        // Shortcut at install root (XXMI-style)
                        new ExeFileShortcut("XXAR", @"[INSTALLDIR]Resources\Bin\XXAR.exe", "")
                        {
                            IconFile = appExe,
                            WorkingDirectory = "BIN_DIR",
                        }),
                    // Start Menu shortcut
                    new Dir(@"%ProgramMenu%\XXAR",
                        new ExeFileShortcut("XXAR", @"[INSTALLDIR]Resources\Bin\XXAR.exe", "")
                        {
                            IconFile = appExe,
                            Description = "Cross-game Audio Replacer",
                            WorkingDirectory = "BIN_DIR",
                        }),
                    // Desktop shortcut (gated by INSTALLDESKTOPSHORTCUT=1 — default on)
                    new Dir(new Id("DesktopFolderDir"), @"%Desktop%",
                        new ExeFileShortcut("XXAR", @"[INSTALLDIR]Resources\Bin\XXAR.exe", "")
                        {
                            IconFile = appExe,
                            Condition = new Condition("INSTALLDESKTOPSHORTCUT=\"1\""),
                            WorkingDirectory = "BIN_DIR",
                        }),
                },
                // Registry marker read by update_manager_bridge._is_msi_install()
                RegValues = new[]
                {
                    new RegValue(RegistryHive.CurrentUser, @"Software\XXAR",
                                 "InstallLocation", "[INSTALLDIR]"),
                    new RegValue(RegistryHive.CurrentUser, @"Software\XXAR",
                                 "Version", opts.Version),
                },
                Properties = new[]
                {
                    new Property("INSTALLDESKTOPSHORTCUT", "1") { AttributesDefinition = "Secure=yes" },
                    new Property("ARPHELPLINK", "https://github.com/Entity378/XXAR"),
                    new Property("ARPURLINFOABOUT", "https://github.com/Entity378/XXAR"),
                },
            };

            project.ControlPanelInfo.Manufacturer = "Entity378";
            project.ControlPanelInfo.HelpLink = "https://github.com/Entity378/XXAR";
            project.ControlPanelInfo.ProductIcon = appExe;

            // Custom WPF UI — defined in InstallerUI.cs.
            InstallerUI.Attach(project);

            var msiPath = project.BuildMsi();
            Console.WriteLine($"==> Built: {msiPath}");
            return 0;
        }
    }

    internal class Options
    {
        public string Version { get; set; } = "0.0.0";
        public string BinDir { get; set; } = @"dist\XXAR";
        public string UpdaterDir { get; set; } = @"dist\Updater";
        public string OutputDir { get; set; } = @"dist";

        public static Options Parse(string[] args)
        {
            var o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--version": o.Version = args[++i]; break;
                    case "--bin-dir": o.BinDir = args[++i]; break;
                    case "--updater-dir": o.UpdaterDir = args[++i]; break;
                    case "--output-dir": o.OutputDir = args[++i]; break;
                    default: throw new ArgumentException($"unknown arg: {args[i]}");
                }
            }
            if (o.Version == "0.0.0")
                throw new ArgumentException("--version is required");
            return o;
        }
    }
}
