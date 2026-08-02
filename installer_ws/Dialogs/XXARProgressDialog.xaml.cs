using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using WixSharp;
using WixSharp.CommonTasks;
using WixSharp.UI.Forms;
using WixSharp.UI.WPF;
using WixToolset.Dtf.WindowsInstaller;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARProgressDialog : WpfDialog, IWpfDialog, IProgressDialog
    {
        private Model model;

        public XXARProgressDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            UpdateTitles(ManagedFormHost.Runtime.Session);
            model = new Model { Host = ManagedFormHost };
            DataContext = model;
            // Installed here rather than in InstallerUI because this is the last point before execution starts where Shell is live.
            var shell = ManagedFormHost.Shell;
            if (shell != null)
                shell.MessageDialog = new XXARMessageFilter { Shell = shell };
            model.StartExecute();
        }

        public void UpdateTitles(ISession session)
        {
            if (session.IsUninstalling())
            {
                DialogTitleLabel.Text = "[ProgressDlgTitleRemoving]";
                DialogDescription.Text = "[ProgressDlgTextRemoving]";
            }
            else if (session.IsRepairing())
            {
                DialogTitleLabel.Text = "[ProgressDlgTextRepairing]";
                DialogDescription.Text = "[ProgressDlgTitleRepairing]";
            }
            else
            {
                DialogTitleLabel.Text = "[ProgressDlgTitleInstalling]";
                DialogDescription.Text = "[ProgressDlgTextInstalling]";
            }
            this.Localize();
        }

        public override MessageResult ProcessMessage(InstallMessage messageType, Record messageRecord,
            MessageButtons buttons, MessageIcon icon, MessageDefaultButton defaultButton)
            => model?.ProcessMessage(messageType, messageRecord) ?? MessageResult.None;

        public override void OnExecuteComplete() => model?.OnExecuteComplete();

        public override void OnProgress(int progressPercentage)
        {
            if (model != null) model.ProgressValue = progressPercentage;
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            // Immediate feedback — MSI cancellation is cooperative and takes a moment.
            if (sender is System.Windows.Controls.Button b) b.IsEnabled = false;
            model?.Cancel();
        }

        private class Model : INotifyPropertyChanged
        {
            public ManagedForm Host;
            private ISession session => Host?.Runtime?.Session;
            private IManagedUIShell shell => Host?.Shell;

            private string currentAction;
            private int progressValue;
            private bool cancelRequested;

            public string CurrentAction
            {
                get => currentAction;
                set { currentAction = value; OnChanged(); }
            }

            public int ProgressValue
            {
                get => progressValue;
                set { progressValue = value; OnChanged(); }
            }

            public void StartExecute() => shell?.StartExecute();

            public void Cancel()
            {
                if (shell != null && shell.IsDemoMode) { shell.GoNext(); return; }
                cancelRequested = true;
                CurrentAction = "Canceling…";
                shell?.Cancel();
            }

            public MessageResult ProcessMessage(InstallMessage messageType, Record messageRecord)
            {
                // Cancel clicked: abort the running install immediately instead of at InstallFinalize.
                // WixSharp's default only cancels via a mutex read there, which is too late.
                if (cancelRequested) return MessageResult.Cancel;
                switch (messageType)
                {
                    case InstallMessage.ActionStart:
                        try
                        {
                            if (messageRecord != null && messageRecord.FieldCount >= 3)
                                CurrentAction = messageRecord[2]?.ToString();
                            else
                                CurrentAction = null;
                        }
                        catch
                        {
                            // Swallowed so a malformed message never crashes the installer.
                        }
                        break;
                }
                return MessageResult.OK;
            }

            public void OnExecuteComplete()
            {
                CurrentAction = null;
                shell?.GoNext();
            }

            public event PropertyChangedEventHandler PropertyChanged;
            private void OnChanged([CallerMemberName] string name = null)
                => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
