
// MainFrm.h : interface of the CMainFrame class
//

#pragma once

class CMainFrame : public CMDIFrameWnd
{
	DECLARE_DYNAMIC(CMainFrame)
public:
	CMainFrame() noexcept;

// Attributes
public:

// Operations
public:

private:
  void generate_log();
  void experiment_perform();

// Overrides
public:
	virtual BOOL PreCreateWindow(CREATESTRUCT& cs);

// Implementation
public:
	virtual ~CMainFrame();
#ifdef _DEBUG
	virtual void AssertValid() const;
	virtual void Dump(CDumpContext& dc) const;
#endif

protected:  // control bar embedded members
	CToolBar          m_wndToolBar;
	CStatusBar        m_wndStatusBar;

// Generated message map functions
protected:
	afx_msg int OnCreate(LPCREATESTRUCT lpCreateStruct);
	DECLARE_MESSAGE_MAP()

public:
    afx_msg void OnFileOpen();
    afx_msg void OnUpdateFileSave(CCmdUI* pCmdUI);
//    afx_msg void OnUpdateFileNew(CCmdUI* pCmdUI);
//    afx_msg void OnFileNew();
    afx_msg void OnUpdateFileOpen(CCmdUI* pCmdUI);
    afx_msg void OnClose();
    afx_msg void OnTaskgenerationGenerationEmpty();
    afx_msg void OnTaskgenerationGeneration();
    afx_msg void OnButtonExperiment();
    afx_msg void OnExperimentPerform();
    virtual BOOL PreTranslateMessage(MSG* pMsg);
};


