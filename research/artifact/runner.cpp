#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#ifdef _MSC_VER
#include <intrin.h>
#endif

using U = uint64_t;
using I = uint32_t;
using Clock = std::chrono::steady_clock;
using Time = Clock::time_point;
static_assert(sizeof(I)==4 && sizeof(U)==8,"Unexpected word sizes");
static U ns(Time a,Time b){return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();}
static unsigned pop(U x){
#ifdef _MSC_VER
    return (unsigned)__popcnt64(x);
#else
    return __builtin_popcountll(x);
#endif
}
static U low(unsigned k){return k==64 ? ~U(0) : (U(1)<<k)-1;}
struct Pred {
    U missing=0,present=0;
    bool accepts(U x) const {return (missing&present)==0 && (x&missing)==missing && !(x&present);}
};
struct Slice {I l,r;};
struct Query {std::string id; Pred p; std::vector<Slice> slices;};
static std::vector<U> read_rows(const std::string& path){
    std::ifstream in(path,std::ios::binary|std::ios::ate); if(!in)throw std::runtime_error("Cannot open "+path);
    auto bytes=static_cast<int64_t>(in.tellg());
    if(bytes<=0 || bytes%8 || U(bytes)/8>UINT32_MAX)throw std::runtime_error("Require 1..2^32-1 uint64 rows");
    std::vector<U> rows(size_t(bytes)/8);in.seekg(0);in.read(reinterpret_cast<char*>(rows.data()),bytes);
    if(!in)throw std::runtime_error("Incomplete row file");return rows;
}
static std::vector<Query> read_queries(const std::string& path,I n){
    std::ifstream fid(path);if(!fid)throw std::runtime_error("Cannot open "+path);
    std::vector<Query> qs;std::unordered_map<std::string,size_t> by_id;std::string line;
    while(std::getline(fid,line)){
        if(line.empty() || line[0]=='#')continue;
        std::istringstream s(line);std::string id;U a,b,l,r; if(!(s>>id>>a>>b>>l>>r) || l>r || r>n)throw std::runtime_error("Invalid .queries row: "+line);
        auto t=by_id.emplace(id,qs.size());
        if(t.second)qs.push_back({id,{a,b},{}});
        auto &q=qs[t.first->second];if(q.p.missing!=a || q.p.present!=b)throw std::runtime_error("Predicate changed for same id");
        q.slices.push_back({I(l),I(r)});
    }return qs;
}
struct Node {int left=-1,right=-1,parent=-1,depth=0,bit=-1; U value=0; I count=0; bool leaf()const{return left<0;}};
struct Tree {
    std::vector<Node> a;
    std::unordered_map<U,int> by_value;
    std::vector<int> leaves;
    U var=0;
    int root=-1; I n;
    int construct(std::vector<std::pair<U,I>>& v,size_t lo,size_t hi,int depth){
        if(hi-lo==1){
            int i=int(a.size());a.push_back({-1,-1,-1,depth,-1,v[lo].first,v[lo].second});
            by_value[v[lo].first]=i;leaves.push_back(i);return i;
        }
        U varies=0;for(size_t i=lo+1;i<hi;++i)varies|=v[i].first^v[lo].first;
        size_t best=hi-lo;int bit=-1;
        for(int b=0;b<64;++b)if(varies&(U(1)<<b)){
            size_t ones=0;for(size_t i=lo;i<hi;++i)ones+=(v[i].first>>b)&1;
            size_t score=std::max(ones,hi-lo-ones); if(score<best){best=score;bit=b;}
        }
        if(bit<0)throw std::logic_error("Expected distinct shapes");
        U bm=U(1)<<bit;size_t mid=std::partition(v.begin()+lo,v.begin()+hi,[&](auto &x){return !(x.first&bm);})-v.begin();
        int left=construct(v,lo,mid,depth+1),right=construct(v,mid,hi,depth+1),i=int(a.size());
        a.push_back({left,right,-1,depth,bit,0,I(a[left].count+a[right].count)});
        a[left].parent=a[right].parent=i;return i;
    }
    explicit Tree(const std::vector<U>& rows):n((I)rows.size()){
        std::unordered_map<U,I> freq;for(U x:rows){++freq[x];var|=x^rows[0];}
        std::vector<std::pair<U,I>> sorted(freq.begin(),freq.end());std::sort(sorted.begin(),sorted.end());
        root=construct(sorted,0,sorted.size(),0);
    }
    U bytes()const{return U(a.size())*sizeof(Node)+U(leaves.size())*sizeof(int);}
};
struct Bits {
    std::vector<U> words;std::vector<I> prefix;
    void init(I n){words.assign((U(n)+63)/64,0);}
    void set(I i){words[i>>6]|=U(1)<<(i&63);}
    void finish(){prefix.resize(words.size()+1);prefix[0]=0;for(size_t i=0;i<words.size();++i)prefix[i+1]=prefix[i]+pop(words[i]);}
    I rank(I i)const{size_t w=i>>6;unsigned k=i&63;return prefix[w]+(k?pop(words[w]&low(k)):0);}
    I range(Slice s)const{return rank(s.r)-rank(s.l);}
    U bytes()const{return 8*words.size()+4*prefix.size();}
};
enum class Storage {post,hybrid,thin,leaf};
struct Counter {std::vector<I> positions; Bits bits; bool dense=false;};
struct Index {
    const Tree &t;Storage mode;std::vector<Counter> v;U payload=0,metadata=0;
    bool allowed(int i)const{
        if(i==t.root)return false;
        return mode==Storage::leaf?t.a[i].leaf():mode!=Storage::thin || t.a[i].leaf() || t.a[i].depth%2==0;
    }
    Index(const Tree &t_,const std::vector<U>& rows,Storage mode_):t(t_),mode(mode_),v(t.a.size()){
        U dense_cost=12*((U(t.n)+63)/64)+4;
        for(int i=0;i<(int)v.size();++i)if(allowed(i)){
            auto &c=v[i];c.dense=(mode==Storage::hybrid && dense_cost<U(t.a[i].count)*4);
            if(c.dense)c.bits.init(t.n);else c.positions.reserve(t.a[i].count);
        }
        for(I r=0;r<t.n;++r){
            int i=t.by_value.at(rows[r]);for(;i!=t.root;i=t.a[i].parent){
                if(allowed(i)){if(v[i].dense)v[i].bits.set(r);else v[i].positions.push_back(r);}
                if(mode==Storage::leaf)break;
            }
        }
        for(auto &c:v){if(c.dense)c.bits.finish();payload+=c.bits.bytes()+4*c.positions.size();}
        metadata=t.bytes()+sizeof(Counter)*v.size();
    }
    I count(int i,Slice s)const{auto &c=v[i];if(c.dense)return c.bits.range(s);
        auto b=c.positions.begin(),e=c.positions.end();
        auto l=s.l==0?b:std::lower_bound(b,e,s.l);auto r=s.r==t.n?e:std::lower_bound(l,e,s.r);
        return I(r-l);
    }
};
struct Term{int node,sign;};
struct Plan{bool root=false;std::vector<Term> terms;};
static void add(Plan &p,const Tree &t,int node,int sign){
    if(node==t.root)p.root=sign>0;else p.terms.push_back({node,sign});
}
static constexpr int inf=1000000000;
struct State{std::array<int,2> cost{},label{};};
static Plan signed_plan(const Tree&t,const Index&ix,Pred q){
    std::vector<State> dp(t.a.size());
    for(int i=0;i<(int)t.a.size();++i){
        const auto &n=t.a[i];auto &d=dp[i];int sub[2];
        for(int x=0;x<2;++x)sub[x]=n.leaf()?(q.accepts(n.value)==bool(x)?0:inf):
                                dp[n.left].cost[x]+dp[n.right].cost[x];
        for(int p=0;p<2;++p){
            int change=i==t.root?0:ix.allowed(i)?1:inf;
            d.label[p]=(sub[1-p]+change<sub[p])?1-p:p;
            d.cost[p]=std::min(sub[p],sub[1-p]+change);
        }
    }
    Plan plan;
    auto walk=[&](auto&& self,int i,int p)->void {int x=dp[i].label[p];if(x!=p)add(plan,t,i,x?1:-1);
        const auto &n=t.a[i];if(!n.leaf()){self(self,n.left,x);self(self,n.right,x);}
    }; walk(walk,t.root,0);return plan;
}
static std::vector<int8_t> labels(const Tree&t,Pred q){
    std::vector<int8_t> v(t.a.size());
    for(int i=0;i<(int)v.size();++i){
        auto &n=t.a[i];v[i]=n.leaf()?q.accepts(n.value):v[n.left]==v[n.right]?v[n.left]:-1;
    }return v;
}
static Plan positive(const Tree&t,const std::vector<int8_t>&v,bool comp){
    Plan p;p.root=comp;
    if(v[t.root]!=-1){p.root=v[t.root]!=0;return p;}
    auto walk=[&](auto&&self,int i)->void{
        if(v[i]>=0){if(bool(v[i])!=comp)add(p,t,i,comp?-1:1);return;}
        self(self,t.a[i].left);self(self,t.a[i].right);
    };walk(walk,t.root);return p;
}
static Plan dictionary(const Tree&t,Pred q){
    size_t hits=0;for(int i:t.leaves)hits+=q.accepts(t.a[i].value);
    Plan p;p.root=hits>t.leaves.size()/2;
    for(int i:t.leaves)if(q.accepts(t.a[i].value)!=p.root)add(p,t,i,p.root?-1:1);
    return p;
}
static I run_plan(const Plan&p,const Index&i,Slice s){
    int64_t ans=p.root?int64_t(s.r-s.l):0;
    for(auto term:p.terms)ans+=term.sign*int64_t(i.count(term.node,s));
    if(ans<0 || ans>s.r-s.l)throw std::logic_error("Invalid signed count");return I(ans);
}


struct Wavelet {
    const Tree &t;std::vector<Bits> split;U payload=0,metadata=0;
    void build(int i,std::vector<U> rows){
        const auto &nd=t.a[i];if(nd.leaf())return; auto &bits=split[i];bits.init(I(rows.size()));
        std::vector<U> a,b;a.reserve(t.a[nd.left].count);b.reserve(t.a[nd.right].count);
        for(I j=0;j<rows.size();++j){if((rows[j]>>nd.bit)&1){bits.set(j);b.push_back(rows[j]);}else a.push_back(rows[j]);}
        bits.finish();payload+=bits.bytes();build(nd.left,std::move(a));build(nd.right,std::move(b));
    }
    Wavelet(const Tree&tree,const std::vector<U>&rows):t(tree),split(t.a.size()){build(t.root,rows);metadata=t.bytes()+sizeof(Bits)*split.size();}
    I count(int i,Slice s,const std::vector<int8_t>&v)const{
        if(s.l==s.r || v[i]==0)return 0;if(v[i]==1)return s.r-s.l;
        const auto &b=split[i];I l=b.rank(s.l),r=b.rank(s.r);const auto &n=t.a[i];
        return count(n.left,{I(s.l-l),I(s.r-r)},v)+count(n.right,{l,r},v);
    }
};
struct Clause {bool zero=false;std::vector<std::pair<const Bits*,bool>> literals;};
struct Columns {
    std::array<Bits,64> bits;U any=0,all=~U(0),payload=0,metadata=sizeof(bits);I n;
    explicit Columns(const std::vector<U>&rows):n(I(rows.size())){
        for(U v:rows){any|=v;all&=v;}
        for(int b=0;b<64;++b)if(((any^all)>>b)&1){
            auto &bit=bits[b];bit.init(n);
            for(I j=0;j<n;++j)if((rows[j]>>b)&1)bit.set(j);
            bit.finish();payload+=bit.bytes();
        }
    }
    Clause prepare(Pred p)const{
        Clause c;c.zero=(p.missing&p.present) || (p.missing&~any) || (p.present&all);if(c.zero)return c;
        for(int b=0;b<64;++b){U bm=U(1)<<b;if((any^all)&bm){
            if(p.missing&bm)c.literals.push_back({&bits[b],true});
            if(p.present&bm)c.literals.push_back({&bits[b],false});
        }}return c;
    }
    static U word(const Clause &c,size_t w){
        U v=~U(0);for(auto [b,s]:c.literals){U x=b->words[w];v&=s?x:~x;}return v;
    }
    I count(const Clause &c,Slice s)const{
        if(s.l==s.r || c.zero)return 0;if(c.literals.empty())return s.r-s.l;
        if(c.literals.size()==1){auto [b,pos]=c.literals.front();I k=b->range(s);return pos?k:s.r-s.l-k;}
        size_t lo=s.l>>6,hi=(s.r-1)>>6;U total=0;
        for(size_t w=lo;w<=hi;++w){U value=word(c,w);if(w==lo)value&=~low(s.l&63);if(w==hi && (s.r&63))value&=low(s.r&63);total+=pop(value);}
        return I(total);
    }
    Bits materialize(const Clause &c)const{
        Bits result;if(c.literals.size()<2 || c.zero)return result;
        result.init(n);for(size_t w=0;w<result.words.size();++w)result.words[w]=word(c,w);
        if(n%64)result.words.back()&=low(n%64);result.finish();return result;
    }
};
static I scan(const std::vector<U>&rows,Pred p,Slice s){
    if(p.missing&p.present)return 0;U mask=p.present|p.missing;I k=0;
    for(size_t j=s.l;j<s.r;++j)k+=((rows[j]&mask)==p.missing);return k;
}
struct Histogram {
    I step=1024,n;std::vector<U> shapes;std::vector<I> hist;const std::vector<U>&rows;U payload=0,metadata=0;
    explicit Histogram(const std::vector<U>&r):n(I(r.size())),rows(r){
        std::unordered_map<U,size_t> id;
        for(U v:r){auto a=id.emplace(v,id.size());if(a.second)shapes.push_back(v);}
        const size_t cap=64u*1024u*1024u;size_t d=shapes.size();
        while((U(n)/step+1)*d*4>cap && step<n)step=I(std::min<U>(n,U(step)*2));
        size_t nb=size_t(n)/step+1;hist.assign(nb*d,0);std::vector<I> counts(d);
        for(I j=0;j<n;++j){++counts[id.at(r[j])];if((j+1)%step==0)std::copy(counts.begin(),counts.end(),hist.begin()+size_t((j+1)/step)*d);}
        payload=8*r.size()+8*d+4*hist.size();metadata=sizeof(*this);
    }
    std::pair<bool,std::vector<size_t>> prepare(Pred p)const{
        size_t k=0;for(U v:shapes)k+=p.accepts(v);bool comp=k>shapes.size()/2;
        std::vector<size_t> ix;for(size_t i=0;i<shapes.size();++i)if(p.accepts(shapes[i])!=comp)ix.push_back(i);
        return {comp,std::move(ix)};
    }
    I count(Pred p,const std::pair<bool,std::vector<size_t>>&h,Slice s)const{
        if(h.second.empty())return h.first?s.r-s.l:0;
        size_t bl=(U(s.l)+step-1)/step,br=s.r/step;
        if(bl>=br)return scan(rows,p,s);
        size_t d=shapes.size();I v=0;
        for(size_t i:h.second)v+=hist[br*d+i]-hist[bl*d+i];
        if(h.first)v=I((br-bl)*step-v);
        return v+scan(rows,p,{s.l,I(bl*step)})+scan(rows,p,{I(br*step),s.r});
    }
};
enum Method{Signed,Hybrid,Thin,Positive,Global,PosHybrid,GlobalHybrid,Leaf,Wave,Bitset,Prefix,Hist,Scan,MethodCount};
const std::array<std::string,MethodCount> names={"signed_post","signed_hybrid","signed_thin","positive","global","positive_hybrid","global_hybrid","leaf","wavelet","bitmap","predicate_prefix","block_hist","scan"};
struct Program {Plan plan;std::vector<int8_t> lab;Clause c;Bits pref;std::pair<bool,std::vector<size_t>> h;};
struct Bench {
    const std::vector<U>& rows;const Tree &t;const Index &post,&hyb,&thin,&leaf;
    const Wavelet &wave;const Columns &cols;const Histogram &hist;
    Program compile(Method m,Pred p) const {
        Program b;
        switch(m){
        case Signed:case Hybrid:case Thin: b.plan=signed_plan(t,m==Thin?thin:m==Hybrid?hyb:post,p);break;
        case Positive:case Global:case PosHybrid:case GlobalHybrid:{auto v=labels(t,p);b.plan=positive(t,v,false);if(m==Global || m==GlobalHybrid){auto neg=positive(t,v,true);if(neg.terms.size()<b.plan.terms.size())b.plan=std::move(neg);}break;}
        case Leaf:b.plan=dictionary(t,p);break;
        case Wave:b.lab=labels(t,p);break;
        case Bitset:case Prefix:b.c=cols.prepare(p);if(m==Prefix)b.pref=cols.materialize(b.c);break;
        case Hist:b.h=hist.prepare(p);break;
        default:break;
        }return b;
    }
    I run(Method m,const Program& b,Pred p,Slice s)const{
        switch(m){
        case Signed:case Positive:case Global:return run_plan(b.plan,post,s);
        case PosHybrid:case GlobalHybrid:case Hybrid:return run_plan(b.plan,hyb,s);case Thin:return run_plan(b.plan,thin,s);
        case Leaf:return run_plan(b.plan,leaf,s);case Wave:return wave.count(t.root,s,b.lab);
        case Prefix:if(!b.pref.words.empty())return b.pref.range(s);[[fallthrough]];
        case Bitset:return cols.count(b.c,s);
        case Hist:return hist.count(p,b.h,s);case Scan:return scan(rows,p,s);default:throw std::logic_error("Invalid method");
        }
    }
};
static U checksum(const std::vector<I>&out){
    U h=14695981039346656037ull;for(I x:out)h=(h^x)*1099511628211ull;return h;
}
static int run(int argc,char**argv){
    if(argc<3 || argc>4)throw std::runtime_error("Usage: runner.exe prefix output.tsv [repeats=3]");
    int reps=argc==4?std::stoi(argv[3]):3;if(reps<1)throw std::runtime_error("Positive repeat count required");
    std::string prefix=argv[1],outpath=argv[2];
    auto rows=read_rows(prefix+".rows");auto queries=read_queries(prefix+".queries",I(rows.size()));
    if(queries.empty())throw std::runtime_error("Empty workload");
    auto start=Clock::now(); Tree tree(rows);U tree_ns=ns(start,Clock::now());
    std::ofstream idx(outpath+".index.tsv");if(!idx)throw std::runtime_error("Cannot open index output");
    idx<<"method\trows\tshapes\tnodes\tpayload_bytes\tmetadata_bytes\tbuild_ns\tblock_size\n";
    auto index_row=[&](std::string name,U data,U meta,U dt,I block=0){
        idx<<name<<'\t'<<rows.size()<<'\t'<<tree.leaves.size()<<'\t'<<tree.a.size()<<'\t'<<data<<'\t'<<meta<<'\t'<<dt<<'\t'<<block<<'\n';
    };
    start=Clock::now();Index post(tree,rows,Storage::post);U ptime=tree_ns+ns(start,Clock::now());
    for(Method m:{Signed,Positive,Global})index_row(names[m],post.payload,post.metadata,ptime);
    start=Clock::now();Index hybrid(tree,rows,Storage::hybrid);U htime=tree_ns+ns(start,Clock::now()); for(Method m:{Hybrid,PosHybrid,GlobalHybrid})index_row(names[m],hybrid.payload,hybrid.metadata,htime);
    start=Clock::now();Index thin(tree,rows,Storage::thin);index_row(names[Thin],thin.payload,thin.metadata,tree_ns+ns(start,Clock::now()));
    start=Clock::now();Index leaf(tree,rows,Storage::leaf);index_row(names[Leaf],leaf.payload,leaf.metadata,tree_ns+ns(start,Clock::now()));
    start=Clock::now();Wavelet wave(tree,rows);index_row(names[Wave],wave.payload,wave.metadata,tree_ns+ns(start,Clock::now()));
    start=Clock::now();Columns cols(rows);U ctime=ns(start,Clock::now());
    for(Method m:{Bitset,Prefix})index_row(names[m],cols.payload,cols.metadata,ctime);
    start=Clock::now();Histogram hist(rows);index_row(names[Hist],hist.payload,hist.metadata,ns(start,Clock::now()),hist.step);
    index_row(names[Scan],rows.size()*8,0,0);idx.close();
    Bench bench{rows,tree,post,hybrid,thin,leaf,wave,cols,hist};
    std::ofstream out(outpath);if(!out)throw std::runtime_error("Cannot open query output");
    out<<"query\tmethod\trepeat\tslices\tterms\tnegative\troot_one\tcompile_ns\texec_ns\tchecksum\tmatched_sum\textra_bytes\n";
    std::mt19937 rand(20261109u);std::vector<int> order(MethodCount);std::iota(order.begin(),order.end(),0);
    for(auto &q:queries){
        std::vector<I> expected(q.slices.size()),actual(expected.size());
        for(size_t j=0;j<expected.size();++j)expected[j]=scan(rows,q.p,q.slices[j]);
        U target_sum=std::accumulate(expected.begin(),expected.end(),U(0)),digest=checksum(expected);
        for(int rep=0;rep<reps;++rep){
            std::shuffle(order.begin(),order.end(),rand);
            for(int mi:order){
                Method m=Method(mi);auto p0=Clock::now();auto prog=bench.compile(m,q.p);auto p1=Clock::now();
                for(size_t j=0;j<actual.size();++j)actual[j]=bench.run(m,prog,q.p,q.slices[j]);
                auto p2=Clock::now();
                if(actual!=expected)throw std::logic_error("Count mismatch: "+q.id+" / "+names[m]);
                int terms=m<=Leaf?int(prog.plan.terms.size()):-1;int neg=m<=Leaf?int(std::count_if(prog.plan.terms.begin(),prog.plan.terms.end(),[](auto &t){return t.sign<0;})):-1;
                out<<q.id<<'\t'<<names[m]<<'\t'<<(rep+1)<<'\t'<<actual.size()<<'\t'<<terms<<'\t'<<neg<<'\t'<<(m<=Leaf?int(prog.plan.root):-1)<<'\t'<<ns(p0,p1)<<'\t'<<ns(p1,p2)<<'\t'<<digest<<'\t'<<target_sum<<'\t'<<prog.pref.bytes()<<'\n';
            }
        }
    }return 0;
}
int main(int argc,char**argv){try{return run(argc,argv);}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
