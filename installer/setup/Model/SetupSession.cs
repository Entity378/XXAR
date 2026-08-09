using System.Diagnostics;

using XXAR.Wizard;

namespace XXAR.Setup
{
    // What the machine looked like when the installer started. Fixed for the whole run.
    public class MachineState
    {
        public string ExecutablePath { get; private set; }
        public long ArchiveOffset { get; private set; }
        public string OfferedVersion { get; private set; }
        public string InstalledRoot { get; private set; }
        public string InstalledVersion { get; private set; }

        public bool CarriesPayload { get { return ArchiveOffset > 0; } }
        public bool IsInstalled { get { return InstalledRoot != null; } }
        public bool IsSameVersionInstalled { get { return IsInstalled && InstalledVersion == OfferedVersion; } }

        public static MachineState Inspect()
        {
            var state = new MachineState();
            state.ExecutablePath = Process.GetCurrentProcess().MainModule.FileName;
            state.ArchiveOffset = SelfExtract.FindArchiveOffset(state.ExecutablePath);
            // The build stamps the release version into this executable's version resource.
            state.OfferedVersion = FileVersionInfo.GetVersionInfo(state.ExecutablePath).ProductVersion ?? "";
            state.InstalledRoot = InstallRecord.ReadInstalledRoot();
            state.InstalledVersion = state.InstalledRoot == null ? null : InstallRecord.ReadInstalledVersion();
            return state;
        }
    }

    // The machine state plus the choices the user makes while stepping through the wizard.
    public class SetupSession
    {
        public MachineState Machine { get; private set; }
        public bool RemoveOnly { get; private set; }

        public string TargetRoot { get; set; }
        public bool PurgeUserData { get; set; }
        public string FailureText { get; set; }

        public static SetupSession Start(bool forceRemove)
        {
            var machine = MachineState.Inspect();
            var session = new SetupSession
            {
                Machine = machine,
                // Without a payload there is nothing to install, so removal is the only thing left to offer.
                RemoveOnly = forceRemove || !machine.CarriesPayload,
                TargetRoot = (machine.InstalledRoot ?? InstallLocations.DefaultRoot).TrimEnd('\\'),
            };

            Journal.Info($"exe={machine.ExecutablePath} payload={(machine.CarriesPayload ? "yes" : "no")} " +
                         $"offered={machine.OfferedVersion} " +
                         $"installed={(machine.IsInstalled ? machine.InstalledRoot + " v" + machine.InstalledVersion : "no")}");
            return session;
        }
    }
}
