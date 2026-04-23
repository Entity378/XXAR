using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows;
using WixSharp;
using WixSharp.UI.WPF;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARInstallDirDialog : WpfDialog, IWpfDialog
    {
        private Model model;

        public XXARInstallDirDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            model = new Model { Host = ManagedFormHost };
            DataContext = model;
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => model.GoPrev();
        private void GoNext_Click(object sender, RoutedEventArgs e) => model.GoNext();
        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();
        private void Change_Click(object sender, RoutedEventArgs e) => model.ChangeInstallDir();

        private class Model : INotifyPropertyChanged
        {
            public WixSharp.UI.Forms.ManagedForm Host;
            private ISession session => Host?.Runtime?.Session;
            private IManagedUIShell shell => Host?.Shell;
            private string installDirProperty => session?.Property("WixSharp_UI_INSTALLDIR");

            public string InstallDirPath
            {
                get
                {
                    if (Host == null) return null;
                    var value = session.Property(installDirProperty);
                    if (string.IsNullOrEmpty(value))
                    {
                        value = session.GetDirectoryPath(installDirProperty);
                        if (value == "ABSOLUTEPATH")
                            value = session.Property("INSTALLDIR_ABSOLUTEPATH");
                    }
                    return ResolveSymbolicPath(value);
                }
                set
                {
                    if (session != null)
                        session[installDirProperty] = value;
                    OnChanged();
                }
            }

            // WixSharp hands us a human-readable symbolic form of the install
            // path (e.g. "LocalApp\XXAR") rather than a fully-resolved one
            // until the user opens the browse dialog. Resolve the common
            // SpecialFolder prefixes so the TextBox shows an absolute path.
            private static string ResolveSymbolicPath(string path)
            {
                if (string.IsNullOrEmpty(path) || Path.IsPathRooted(path))
                    return path;

                var localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);

                (string prefix, string baseDir)[] map =
                {
                    ("LocalApp\\",          localApp),
                    ("LocalAppDataFolder\\", localApp),
                    ("[LocalAppDataFolder]", localApp),
                    ("AppData\\",           appData),
                    ("AppDataFolder\\",     appData),
                    ("[AppDataFolder]",     appData),
                    ("ProgramFiles64\\",    programFiles),
                    ("[ProgramFiles64Folder]", programFiles),
                };
                foreach (var (prefix, baseDir) in map)
                {
                    if (path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        return Path.Combine(baseDir, path.Substring(prefix.Length));
                }
                return path;
            }

            public void ChangeInstallDir()
            {
                using (var dialog = new System.Windows.Forms.FolderBrowserDialog { SelectedPath = InstallDirPath })
                {
                    if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
                        InstallDirPath = dialog.SelectedPath;
                }
            }

            public void GoPrev() => shell?.GoPrev();
            public void GoNext() => shell?.GoNext();
            public void Cancel() => shell?.Cancel();

            public event PropertyChangedEventHandler PropertyChanged;
            private void OnChanged([CallerMemberName] string name = null)
                => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
