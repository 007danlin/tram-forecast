// Keep the public fragment IDs used to render selected original station labels.
export default {
  plugins: [
    {
      name: "preset-default",
      params: {
        overrides: {
          cleanupIds: false,
          removeUselessDefs: false,
        },
      },
    },
  ],
};
