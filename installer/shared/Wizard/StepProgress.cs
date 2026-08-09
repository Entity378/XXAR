namespace XXAR.Wizard
{
    // What a running job reports back to the progress step.
    public struct StepProgress
    {
        public readonly int Percent;
        public readonly string Status;

        public StepProgress(int percent, string status)
        {
            Percent = percent;
            Status = status;
        }
    }
}
