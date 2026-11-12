interface Props {
  text: string;
}

export function ArchSummary({ text }: Props) {
  return <p className="font-sans text-base leading-relaxed text-ink">{text}</p>;
}
