import { segmentByTerms } from "@/lib/highlight";

export default function Highlight({ text, terms }: { text: string; terms: string[] }) {
  return (
    <>
      {segmentByTerms(text, terms).map((segment, index) =>
        segment.matched ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>,
      )}
    </>
  );
}
