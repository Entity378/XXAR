using System;
using System.IO;
using WixSharp;
using WixSharp.CommonTasks;
using WixSharp.Controls;

namespace XXAR.Installer
{
    // Build entry point. Produces dist/XXAR-Installer-v<version>.msi.
    public class Setup
    {
        // Stable across versions, or upgrades break. Rotated for 0.8 (install root moved to LocalAppData).
        private static readonly Guid UpgradeCode = new Guid("607A2141-7C0A-415B-9A7C-0C3D214DADF3");

        public static int Main(string[] args)
        {
            var opts = Options.Parse(args);

            if (!Directory.Exists(opts.BinDir))
                throw new DirectoryNotFoundException($"Bin source not found: {opts.BinDir}");

            var appExe = Path.Combine(opts.BinDir, "XXAR.exe");
            if (!System.IO.File.Exists(appExe))
                throw new FileNotFoundException($"XXAR.exe missing in {opts.BinDir}", appExe);

            var licencePath = Path.GetFullPath(@"installer_ws\License.rtf");
            if (!System.IO.File.Exists(licencePath))
                throw new FileNotFoundException($"License file missing: {licencePath}");

            // Strip SemVer prerelease suffix — MSI version is Major.Minor.Build only.
            var msiVersion = new Version(opts.Version.Split('-')[0]);

            var project = new ManagedProject("XXAR")
            {
                UpgradeCode = UpgradeCode,
                Version = msiVersion,
                LicenceFile = licencePath,
                // Per-user install root: %LOCALAPPDATA%\XXAR\
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
                    // Pin INSTALLDIR to the XXAR root, else WixSharp auto-picks the resources\ child and breaks [INSTALLDIR] paths.
                    // The app installs flat under resources\; there is no Bin/Updater split since the MSI updates via msiexec.
                    new Dir(new Id("INSTALLDIR"), @"%LocalAppDataFolder%\XXAR",
                        new Dir(new Id("RESOURCES_DIR"), "resources", new Files(Path.Combine(opts.BinDir, "*.*")))),
                    // Start Menu shortcut
                    new Dir(@"%ProgramMenu%\XXAR",
                        new ExeFileShortcut("XXAR", @"[INSTALLDIR]resources\XXAR.exe", "")
                        {
                            IconFile = appExe,
                            Description = "Cross-game Audio Replacer",
                            WorkingDirectory = "RESOURCES_DIR",
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
                    // Restore the install folder from the previous install so updates keep a custom location.
                    new Property("INSTALLDIR",
                        new RegistrySearch(RegistryHive.CurrentUser, @"Software\XXAR",
                                           "InstallLocation", RegistrySearchType.raw)),
                    // Set to "1" by the in-app updater to show only the progress dialog.
                    new Property("XXAR_SILENT", "0") { AttributesDefinition = "Secure=yes" },
                    // Set to "1" by the maintenance dialog checkbox to also wipe mods + settings on uninstall.
                    new Property("XXAR_PURGE_USERDATA", "0") { AttributesDefinition = "Secure=yes" },
                    new Property("ARPHELPLINK", "https://github.com/Entity378/XXAR"),
                    new Property("ARPURLINFOABOUT", "https://github.com/Entity378/XXAR"),
                },
                Actions = new WixSharp.Action[]
                {
                    // Remove runtime data MSI doesn't track (tools, caches, and optionally mods).
                    // Runs only on a real uninstall, never during a major upgrade, so updates keep tools + mods.
                    new ManagedAction(CustomActions.CleanupXXARData)
                    {
                        Execute = Execute.deferred,
                        Return = Return.ignore,
                        When = When.Before,
                        Step = Step.InstallFinalize,
                        Condition = new Condition("(REMOVE=\"ALL\") AND (NOT UPGRADINGPRODUCTCODE)"),
                        UsesProperties = "LOCAL_XXAR=[LocalAppDataFolder]XXAR,ROAMING_XXAR=[AppDataFolder]XXAR,STARTMENU_XXAR=[ProgramMenuFolder]XXAR,XXAR_PURGE_USERDATA=[XXAR_PURGE_USERDATA]",
                    },
                    // On install/upgrade only, drop a wrongly-cased "Resources" folder left by a pre-flatten install.
                    // It must run before InstallFiles so InstallFiles then recreates the folder lowercase and flat.
                    new ManagedAction(CustomActions.NormalizeResourcesCasing)
                    {
                        Execute = Execute.deferred,
                        Return = Return.ignore,
                        When = When.Before,
                        Step = Step.InstallFiles,
                        Condition = new Condition("NOT (REMOVE=\"ALL\")"),
                        UsesProperties = "INSTALLDIR=[INSTALLDIR]",
                    },
                },
            };

            project.ControlPanelInfo.Manufacturer = "Entity378";
            project.ControlPanelInfo.HelpLink = "https://github.com/Entity378/XXAR";
            project.ControlPanelInfo.ProductIcon = appExe;
            // Hide the separate ARP "Repair" — repair is offered as a tile inside our maintenance dialog.
            project.ControlPanelInfo.NoRepair = true;

            // Custom WPF UI — defined in InstallerUI.cs.
            InstallerUI.Attach(project);

            var msiPath = project.BuildMsi();

            // WixSharp's ManagedUI writes ARPNOMODIFY=1 into the built MSI, which hides the Control Panel "Change" entry.
            // Strip it here so "Change" opens our maintenance dialog (Repair/Remove + purge checkbox).
            using (var db = new WixToolset.Dtf.WindowsInstaller.Database(msiPath, WixToolset.Dtf.WindowsInstaller.DatabaseOpenMode.Direct))
            {
                db.Execute("DELETE FROM `Property` WHERE `Property` = 'ARPNOMODIFY'");
                db.Commit();
            }

            Console.WriteLine($"==> Built: {msiPath}");
            return 0;
        }
    }

    internal class Options
    {
        public string Version { get; set; } = "0.0.0";
        public string BinDir { get; set; } = @"dist\XXAR";
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
