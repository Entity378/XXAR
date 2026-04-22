using System.ComponentModel;
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
                    if (!string.IsNullOrEmpty(value)) return value;
                    var dir = session.GetDirectoryPath(installDirProperty);
                    if (dir == "ABSOLUTEPATH")
                        dir = session.Property("INSTALLDIR_ABSOLUTEPATH");
                    return dir;
                }
                set
                {
                    if (session != null)
                        session[installDirProperty] = value;
                    OnChanged();
                }
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
