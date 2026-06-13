export interface AtomicSkillFn {
  name: string;
  execute: (params: Record<string, string>) => Promise<{ message: string; screenshot?: string }>;
}

/** Browser-level atomic skills registry */
export class SkillRegistry {
  private skills = new Map<string, AtomicSkillFn>();

  constructor(
    private navigateFn: (path: string) => void,
    private screenshotFn: () => Promise<string | null>,
  ) {
    this.registerAll();
  }

  private registerAll(): void {
    this.skills.set('navigate', {
      name: 'navigate',
      execute: async (params) => {
        this.navigateFn(params.path);
        await sleep(500);
        return { message: `已导航到 ${params.path}` };
      },
    });

    this.skills.set('click', {
      name: 'click',
      execute: async (params) => {
        const el = await waitForElement(params.selector, 5000);
        if (!el) throw new Error(`未找到元素: ${params.selector}`);
        (el as HTMLElement).click();
        await sleep(400);
        return { message: `已点击 ${params.selector}` };
      },
    });

    this.skills.set('wait', {
      name: 'wait',
      execute: async (params) => {
        const ms = Number(params.ms) || 500;
        await sleep(ms);
        return { message: `等待 ${ms}ms` };
      },
    });

    this.skills.set('waitForElement', {
      name: 'waitForElement',
      execute: async (params) => {
        await waitForElement(params.selector, Number(params.timeout) || 5000);
        return { message: `元素就绪: ${params.selector}` };
      },
    });

    this.skills.set('screenshot', {
      name: 'screenshot',
      execute: async () => {
        const shot = await this.screenshotFn();
        return { message: '截图完成', screenshot: shot || undefined };
      },
    });
  }

  get(name: string): AtomicSkillFn | undefined {
    return this.skills.get(name);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function waitForElement(selector: string, timeout: number): Promise<Element | null> {
  return new Promise((resolve) => {
    const start = Date.now();
    const check = () => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      if (Date.now() - start > timeout) return resolve(null);
      requestAnimationFrame(check);
    };
    check();
  });
}
