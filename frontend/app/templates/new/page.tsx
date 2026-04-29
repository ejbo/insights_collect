import TemplateEditor from "../[id]/page";

export default function NewTemplatePage() {
  // Reuse editor with id="new"
  // @ts-ignore — params is a Promise<{id}> in editor; pass static
  return <TemplateEditor params={Promise.resolve({ id: "new" })} />;
}
